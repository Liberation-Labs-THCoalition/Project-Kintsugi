"""BashSkillChip — sandboxed shell execution for Kintsugi agents.

Provides controlled bash access within a companion's workspace. Enforces:
- Dangerous pattern blocklist (from Claude Code scaffold analysis)
- argv-based execution (no shell) so metacharacters can't chain commands
- Working directory confinement to companion workspace
- Timeout enforcement
- Output capture and truncation
- Auto-permission tiers (always allow, ask, never allow)

Every Kintsugi deployment (Ayni, Scout, Multiverse, etc.) gets this chip.
The companion can create files, run scripts, and build artifacts that
persist in their workspace.
"""

from __future__ import annotations

import asyncio
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from kintsugi.skills.base import (
    BaseSkillChip, SkillCapability, SkillContext, SkillDomain,
    SkillRequest, SkillResponse, EFEWeights,
)

# Defense-in-depth: rejected outright even though argv execution already
# prevents shell metacharacters (";", "|", "&&", backticks, ...) from being
# interpreted — they're just literal arguments to whatever program runs,
# not command separators. This blocklist catches dangerous *programs*
# being invoked directly (e.g. "sudo rm -rf /").
DANGEROUS_PATTERNS = [
    r'\beval\b', r'\bexec\b', r'\bsudo\b', r'\bsu\b',
    r'\brm\s+-rf\s+/', r'\brm\s+-rf\s+~',
    r'\bmkfs\b', r'\bdd\s+if=', r'\b:(){ :\|:& };:',
    r'\bchmod\s+777\b', r'\bchown\s+root\b',
    r'\b/etc/passwd\b', r'\b/etc/shadow\b',
    r'\bkill\s+-9\s+1\b', r'\bshutdown\b', r'\breboot\b',
    r'\bcurl\b.*\|\s*(?:bash|sh)\b',
    r'\bwget\b.*\|\s*(?:bash|sh)\b',
    r'>\s*/dev/sd[a-z]', r'>\s*/dev/null\s*2>&1\s*&',
    r'\bnc\s+-[le]', r'\bncat\b.*-[le]',
    r'\biptables\b', r'\bufw\b',
    r'\bsystemctl\b', r'\bservice\b',
    r'\bdocker\s+rm\b', r'\bdocker\s+rmi\b',
    r'\bgit\s+push\s+--force\b', r'\bgit\s+reset\s+--hard\b',
]

# Binaries permitted to run without human approval. Checked against the
# resolved program name (argv[0], with any path component stripped), never
# against the raw command string — so no regex-prefix trick can smuggle a
# different program through under a matching prefix.
ALWAYS_ALLOW_BINARIES = frozenset({
    "ls", "head", "tail",
    "wc", "echo", "date", "pwd",
    "sort", "uniq",
    "mkdir", "touch",
    "which", "file", "stat", "du", "df",
})

MAX_OUTPUT_CHARS = 8000
DEFAULT_TIMEOUT = 30


@dataclass
class BashPermission:
    """Permission configuration for bash execution."""
    tier: str = "ask"  # "always_allow", "ask", "never_allow"
    reason: str = ""
    argv: list[str] | None = None


class BashSkillChip(BaseSkillChip):
    """Sandboxed bash execution within a companion's workspace.

    Commands are parsed with ``shlex`` and executed via argv
    (``create_subprocess_exec``), never through a shell. This means shell
    metacharacters are inert — a command like ``"echo hi; rm -rf /"``
    parses into a single argv list (``["echo", "hi;", "rm", "-rf", "/"]``)
    that is passed *entirely* to ``echo`` as literal arguments; there is no
    shell present to interpret ``;`` as a command separator.

    Only a small allowlist of read-only/workspace-local binaries may run
    without explicit approval, and the subprocess environment is scrubbed
    down to a minimal set of variables so host secrets (API keys, DB
    credentials, bot tokens, etc.) are never inherited by child processes.
    """

    name = "bash_executor"
    domain = SkillDomain.SHELL
    description = "Execute shell commands in the companion's workspace"
    version = "1.1.0"
    capabilities = [SkillCapability.EXECUTE_SHELL, SkillCapability.WRITE_DATA]
    efe_weights = EFEWeights()

    def __init__(self, workspace_dir: str = None, timeout: int = DEFAULT_TIMEOUT):
        self.workspace = Path(workspace_dir) if workspace_dir else Path.home() / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self._dangerous_re = [re.compile(p, re.IGNORECASE) for p in DANGEROUS_PATTERNS]

    def _scrubbed_env(self) -> dict[str, str]:
        """Minimal subprocess environment — no host secrets leak through."""
        return {
            "HOME": str(self.workspace),
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8",
        }

    def classify_command(self, command: str) -> BashPermission:
        """Parse and classify a command into permission tiers.

        Parsing happens once, here, and the resulting argv is carried on
        the returned :class:`BashPermission` so ``handle`` executes exactly
        what was classified — there's no window for the classification and
        the execution to disagree about what the command actually is.
        """
        stripped = command.strip()

        for pattern in self._dangerous_re:
            if pattern.search(stripped):
                return BashPermission(
                    tier="never_allow",
                    reason=f"Blocked by safety pattern: {pattern.pattern}",
                )

        try:
            argv = shlex.split(stripped)
        except ValueError as e:
            return BashPermission(
                tier="never_allow",
                reason=f"Unparsable command (unbalanced quotes?): {e}",
            )

        if not argv:
            return BashPermission(tier="never_allow", reason="Empty command")

        program = Path(argv[0]).name  # "/bin/ls" -> "ls", "./ls" -> "ls"

        # Require a bare binary name (no path component) on the allowlist.
        # Rejecting "./ls" or "/some/path/ls" prevents an attacker from
        # reaching an always-allow decision via a same-named binary they
        # planted elsewhere on disk.
        if argv[0] == program and program in ALWAYS_ALLOW_BINARIES:
            return BashPermission(tier="always_allow", reason="Safe read-only command", argv=argv)

        return BashPermission(tier="ask", reason="Requires approval", argv=argv)

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        command = request.raw_input or request.parameters.get("command", "")
        if not command:
            return SkillResponse(
                content="No command provided.",
                success=False,
            )

        permission = self.classify_command(command)

        if permission.tier == "never_allow":
            return SkillResponse(
                content=f"Command blocked: {permission.reason}",
                success=False,
                data={"blocked": True, "reason": permission.reason},
            )

        if permission.tier == "ask":
            if not request.parameters.get("approved", False):
                return SkillResponse(
                    content=f"Command requires approval: `{command}`",
                    success=False,
                    requires_consensus=True,
                    consensus_action="shell_execute",
                    data={"command": command, "reason": permission.reason},
                )

        argv = permission.argv
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace),
                env=self._scrubbed_env(),
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
        except FileNotFoundError:
            return SkillResponse(
                content=f"Command not found: `{argv[0]}`",
                success=False,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return SkillResponse(
                content=f"Command timed out after {self.timeout}s: `{command}`",
                success=False,
                data={"timeout": True},
            )
        except Exception as e:
            return SkillResponse(
                content=f"Execution error: {e}",
                success=False,
            )

        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")

        if len(out) > MAX_OUTPUT_CHARS:
            out = out[:MAX_OUTPUT_CHARS] + f"\n... (truncated, {len(stdout)} bytes total)"
        if len(err) > MAX_OUTPUT_CHARS:
            err = err[:MAX_OUTPUT_CHARS] + f"\n... (truncated)"

        combined = out
        if err:
            combined += f"\nSTDERR:\n{err}"

        return SkillResponse(
            content=combined or "(no output)",
            success=proc.returncode == 0,
            data={
                "exit_code": proc.returncode,
                "stdout_bytes": len(stdout),
                "stderr_bytes": len(stderr),
                "command": command,
                "working_dir": str(self.workspace),
            },
        )

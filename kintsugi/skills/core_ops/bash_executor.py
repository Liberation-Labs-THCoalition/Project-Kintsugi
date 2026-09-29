"""BashSkillChip — sandboxed shell execution for Kintsugi agents.

Provides controlled bash access within a companion's workspace. Enforces:
- Dangerous pattern blocklist (from Claude Code scaffold analysis)
- Working directory confinement to companion workspace
- Timeout enforcement
- Output capture and truncation
- Auto-permission tiers (always allow, ask, never allow)

Every Kintsugi deployment (Ayni, Scout, Multiverse, etc.) gets this chip.
The companion can create files, run scripts, and build artifacts that
persist in their workspace.
"""

import asyncio
import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kintsugi.skills.base import (
    BaseSkillChip, SkillCapability, SkillContext, SkillDomain,
    SkillRequest, SkillResponse, EFEWeights,
)

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

ALWAYS_ALLOW_PATTERNS = [
    r'^ls\b', r'^head\b', r'^tail\b',
    r'^wc\b', r'^echo\b', r'^date\b', r'^pwd\b',
    r'^sort\b', r'^uniq\b',
    r'^mkdir\b', r'^touch\b',
    r'^which\b', r'^file\b', r'^stat\b', r'^du\b', r'^df\b',
]

# The safe tier runs WITHOUT a shell (exec with an argument list), so these
# characters would only be literal arguments there; a command containing any of
# them is not what it looks like, and it leaves the safe tier.
SHELL_OPERATORS = set(";&|`$<>\n\r")
SAFE_COMMANDS = {p.lstrip("^").split("\\b")[0] for p in ALWAYS_ALLOW_PATTERNS}

MAX_OUTPUT_CHARS = 8000
DEFAULT_TIMEOUT = 30


@dataclass
class BashPermission:
    """Permission configuration for bash execution."""
    tier: str = "ask"  # "always_allow", "ask", "never_allow"
    reason: str = ""
    argv: list = field(default_factory=list)   # set for always_allow: what exec runs


class BashSkillChip(BaseSkillChip):
    """Sandboxed bash execution within a companion's workspace."""

    name = "bash_executor"
    domain = SkillDomain.SHELL
    description = "Execute shell commands in the companion's workspace"
    version = "1.0.0"
    capabilities = [SkillCapability.EXECUTE_SHELL, SkillCapability.WRITE_DATA]
    efe_weights = EFEWeights()

    def __init__(self, workspace_dir: str = None, timeout: int = DEFAULT_TIMEOUT):
        self.workspace = Path(workspace_dir) if workspace_dir else Path.home() / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self._dangerous_re = [re.compile(p, re.IGNORECASE) for p in DANGEROUS_PATTERNS]
        self._safe_re = [re.compile(p) for p in ALWAYS_ALLOW_PATTERNS]

    def classify_command(self, command: str) -> BashPermission:
        """Classify a command into permission tiers."""
        stripped = command.strip()

        for pattern in self._dangerous_re:
            if pattern.search(stripped):
                return BashPermission(
                    tier="never_allow",
                    reason=f"Blocked by safety pattern: {pattern.pattern}"
                )

        argv = self._safe_argv(stripped)
        if argv is not None:
            return BashPermission(tier="always_allow", reason="Safe read-only command", argv=argv)

        return BashPermission(tier="ask", reason="Requires approval")

    def _safe_argv(self, command: str):
        """The argument list for a safe-tier command, or None if it is not one.

        Safe means: one allowlisted program, no shell operators, no long options
        or option values carrying paths, and every other argument a relative
        path that resolves inside the workspace (symlinks included). The first
        word alone used to decide, and the whole string then went to a shell.
        """
        if set(command) & SHELL_OPERATORS:
            return None
        try:
            argv = shlex.split(command)
        except ValueError:
            return None
        if not argv or argv[0] not in SAFE_COMMANDS:
            return None
        for arg in argv[1:]:
            if arg.startswith("-"):
                if arg.startswith("--") or any(c in arg for c in "/~="):
                    return None
            elif not self._inside_workspace(arg):
                return None
        return argv

    def _inside_workspace(self, arg: str) -> bool:
        if arg.startswith("~") or Path(arg).is_absolute():
            return False
        try:
            (self.workspace / arg).resolve().relative_to(self.workspace.resolve())
        except ValueError:
            return False
        return True

    def _env(self) -> dict:
        """The subprocess environment: enough to run, none of the server's secrets."""
        return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.workspace),
                "LANG": os.environ.get("LANG", "C.UTF-8")}

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
            # Approval must come from a server-side consensus consumer, and none
            # exists yet, so this tier fails closed. A caller-supplied
            # parameters["approved"] used to authorize it, which let anyone who
            # could reach the API approve their own command (Vera, 2026-09-24).
            return SkillResponse(
                content=f"Command requires approval: `{command}`",
                success=False,
                requires_consensus=True,
                consensus_action="shell_execute",
                data={"command": command, "reason": permission.reason},
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                *permission.argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace),
                env=self._env(),
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
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

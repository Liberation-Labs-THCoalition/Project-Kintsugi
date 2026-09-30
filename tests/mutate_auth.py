"""Mutation check for step 3 (auth, org scoping, admin gating): every rule broken on purpose must fail the tests.

    ~/project-kintsugi/.venv/bin/python tests/mutate_auth.py

Each mutant runs in a fresh copy of the tree. Two gates come first: the copy must import its own `kintsugi` (not this
worktree's), and the unmutated copy must pass. Without them a kill, or a survival, means nothing.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ["tests/test_api_auth.py", "tests/test_framework_api.py", "tests/test_bash_chip_hardening.py"]
MUTANTS = [
    ("kintsugi/main.py", "_deps = [] if _mod_path in PUBLIC_ROUTE_MODULES else [Depends(require_principal)]",
     "_deps = []", "routers mounted without the principal dependency"),
    ("kintsugi/main.py", 'PUBLIC_ROUTE_MODULES = {"kintsugi.api.routes.health"}',
     'PUBLIC_ROUTE_MODULES = {"kintsugi.api.routes.health", "kintsugi.api.routes.oracle"}', "oracle made public"),
    # Not a mutant: removing the dependency from the dashboard's mount in main.py is equivalent, because the
    # dashboard router carries require_admin itself (see "dashboard open to members" below). Defence in depth.
    ("kintsugi/main.py", "allow_credentials=False,", "allow_credentials=True,", "CORS credentials back on"),
    ("kintsugi/config/settings.py", "PUBLIC_DOCS: bool = False", "PUBLIC_DOCS: bool = True", "docs public by default"),
    ("kintsugi/api/auth.py", '''    if not principal.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin key required")''', "",
     "admin check removed"),
    ("kintsugi/api/auth.py", '''    if str(requested) != principal.org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,''', '''    if False:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,''', "a requested org is never refused"),
    ("kintsugi/api/auth.py", "        if not is_loopback(client):", "        if False:",
     "auth-disabled serves any client"),
    ("kintsugi/api/auth.py", 'if scheme.lower() != "bearer" or not token:', "if not token:", "any auth scheme accepted"),
    ("kintsugi/security/api_keys.py", "return found if found is not None and found.revoked_at is None else None",
     "return found", "revoked keys still work"),
    ("kintsugi/security/api_keys.py", "prefix=plaintext[len(PREFIX):len(PREFIX) + 6], key_hash=_hash(plaintext),",
     "prefix=plaintext[len(PREFIX):len(PREFIX) + 6], key_hash=plaintext,", "the key itself is stored"),
    # Not a mutant: opening the temporary file 0644 is equivalent in any test, because the chmod to 0600 that
    # follows sets the final mode; the open mode only narrows a race window no test can observe.
    ("kintsugi/security/api_keys.py", "        os.chmod(tmp, 0o600)\n", "        os.chmod(tmp, 0o644)\n",
     "key file world-readable (chmod)"),
    ("kintsugi/api/routes/fleet.py", '''    if agent.org_id != principal.org_id:
        raise HTTPException(status_code=404, detail=f"unknown agent {agent_id!r}")''', "",
     "another org's agent is reachable by id"),
    ("kintsugi/api/routes/fleet.py", '''                       if a.org_id == principal.org_id]}''', ''']}''',
     "agent listing shows every org"),
    ("kintsugi/api/routes/sessions.py", '''    if body.agent_id is not None:
        own_agent(body.agent_id, principal)''', "", "a session may attach to another org's agent"),
    ("kintsugi/api/routes/sessions.py", '''    if session.org_id != principal.org_id:
        raise HTTPException(status_code=404, detail=f"unknown session {session_id!r}")''', "",
     "another org's session is reachable by id"),
    ("kintsugi/api/routes/oracle.py", '''    if body.name and body.name not in settings.ORACLE_HOOK_ENDPOINTS:
        raise HTTPException(status_code=422, detail=f"unknown Oracle endpoint name {body.name!r}")''', "",
     "unlisted endpoint names accepted"),
    ("kintsugi/api/routes/oracle.py", '''    audit(principal, "oracle.endpoint", new=body.name or "(detached)")''', "",
     "endpoint changes unaudited"),
    ("kintsugi/api/routes/oracle.py", '''    audit(principal, "oracle.mode", old=old, new=body.mode)''', "", "mode changes unaudited"),
    ("kintsugi/api/routes/oracle.py", "principal: Principal = Depends(require_admin)) -> dict:\n    monitor = get_oracle_monitor()\n    old",
     "principal: Principal = Depends(require_principal)) -> dict:\n    monitor = get_oracle_monitor()\n    old",
     "mode switch open to members"),
    ("kintsugi/oracle/hooks.py", "follow_redirects=False", "follow_redirects=True", "the hook follows redirects"),
    ("kintsugi/oracle/hooks.py", '''    if u.scheme == "http" and loopback:''', '''    if u.scheme == "http":''',
     "plaintext hook to a remote host allowed"),
    ("kintsugi/api/routes/events.py", '''router = APIRouter(prefix="/api/v1/events", tags=["events"], dependencies=[Depends(require_admin)])''',
     '''router = APIRouter(prefix="/api/v1/events", tags=["events"])''', "events open to members"),
    ("kintsugi/dashboard/routes.py", '''                   dependencies=[Depends(require_admin)])''', ''')''', "dashboard open to members"),
    ("kintsugi/api/routes/skills.py", '''async def load_plugin(plugin_name: str, principal: Principal = Depends(require_admin)) -> dict:''',
     '''async def load_plugin(plugin_name: str, principal: Principal = Depends(require_principal)) -> dict:''',
     "plugin load open to members"),
    ("kintsugi/api/routes/skills.py", "    org_id = resolve_org(principal, body.org_id)\n", "    org_id = body.org_id\n",
     "skill execution trusts the body's org"),
    ("kintsugi/api/routes/config.py", '''    principal: Principal = Depends(require_admin),
) -> InitResponse:''', '''    principal: Principal = Depends(require_principal),
) -> InitResponse:''', "org creation open to members"),
    ("kintsugi/cli/keys.py", '''        typer.echo(f"{rec.id}  org={rec.org_id}  role={rec.role}  kin_{rec.prefix}...  {state}  {rec.label}")''',
     '''        typer.echo(f"{rec.id}  org={rec.org_id}  role={rec.role}  {rec.key_hash}  {state}  {rec.label}")''',
     "listing prints the stored hash"),
]


def copy(td: str) -> Path:
    d = Path(td) / "k"
    shutil.copytree(ROOT, d, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache", "*.pyc"))
    return d


def run(d: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *TESTS], cwd=d,
                          capture_output=True, text=True, timeout=900)


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = copy(td)
        where = subprocess.run([sys.executable, "-c", "import kintsugi; print(kintsugi.__file__)"], cwd=d,
                               capture_output=True, text=True).stdout.strip()
        if not where.startswith(str(d)):
            sys.exit(f"IMPORT GATE FAILS: the copy imports {where}, not its own tree")
        base = run(d)
        if base.returncode != 0:
            sys.exit("BASELINE FAILS: the unmutated copy does not pass\n" + base.stdout[-2000:])
    print("import gate and baseline pass")
    survived = []
    for n, (f, old, new, why) in enumerate(MUTANTS, 1):
        with tempfile.TemporaryDirectory() as td:
            d = copy(td)
            p = d / f
            s = p.read_text()
            if s.count(old) != 1:
                print(f"M{n:02d} BAD MUTANT ({s.count(old)}x): {why}")
                survived.append(why)
                continue
            p.write_text(s.replace(old, new))
            killed = run(d).returncode != 0
            print(f"M{n:02d} {'killed ' if killed else 'SURVIVED'} {why}", flush=True)
            if not killed:
                survived.append(why)
    print(f"\n{len(MUTANTS) - len(survived)}/{len(MUTANTS)} killed")
    sys.exit(1 if survived else 0)


if __name__ == "__main__":
    main()

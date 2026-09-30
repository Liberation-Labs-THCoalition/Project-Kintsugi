"""Route guards shared by every API path that can run a skill.

No route authenticates yet, so no request may reach a shell-capable skill.
Keyed on capability, not name: a renamed shell chip is still a shell
(Vera, 2026-09-29). Lift this only behind authentication.
"""
from fastapi import HTTPException

from kintsugi.skills.base import SkillCapability


def refuse_shell_capable(registry, skill_names, route: str) -> None:
    """Raise 403 if any named skill resolves to a shell-capable chip."""
    shell = []
    for name in skill_names or []:
        chip = registry.get(name)
        if chip is not None and SkillCapability.EXECUTE_SHELL in chip.capabilities:
            shell.append(name)
    if shell:
        raise HTTPException(
            status_code=403,
            detail=f"{route}: shell-capable skills {shell} are disabled until this API "
                   "has authentication")

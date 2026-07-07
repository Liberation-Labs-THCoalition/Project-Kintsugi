"""Register all built-in skill chips into the global registry.

Called at server startup so `kintsugi serve` comes up with the full
chip catalog. Individual chip import failures are logged and skipped —
one broken chip must not keep the framework down.
"""

from __future__ import annotations

import importlib
import inspect
import logging

from kintsugi.skills.base import BaseSkillChip
from kintsugi.skills.registry import get_registry

logger = logging.getLogger(__name__)

_CHIP_PACKAGES = [
    "kintsugi.skills.core_ops",
    "kintsugi.skills.programs_people",
    "kintsugi.skills.community_aid",
]


def register_builtin_chips() -> list[str]:
    """Instantiate and register every chip class exported by the built-in
    skill packages. Idempotent: already-registered names are skipped.

    Returns the names of newly registered chips.
    """
    registry = get_registry()
    registered: list[str] = []

    for package_name in _CHIP_PACKAGES:
        try:
            package = importlib.import_module(package_name)
        except Exception as exc:
            logger.warning("skill package %s failed to import: %s", package_name, exc)
            continue

        for attr_name in dir(package):
            obj = getattr(package, attr_name)
            if (
                inspect.isclass(obj)
                and issubclass(obj, BaseSkillChip)
                and obj is not BaseSkillChip
            ):
                try:
                    chip = obj()
                except Exception as exc:
                    logger.warning("chip %s failed to instantiate: %s", attr_name, exc)
                    continue
                if registry.get(chip.name) is not None:
                    continue
                try:
                    registry.register(chip)
                    registered.append(chip.name)
                except Exception as exc:
                    logger.warning("chip %s failed to register: %s", chip.name, exc)

    if registered:
        logger.info("registered %d built-in skill chips", len(registered))
    return registered

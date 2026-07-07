"""Agent personality definitions loaded from YAML or TOML.

A personality is the declarative configuration of one agent archetype:
identity, EFE weight profile, which skills it may use, and its safety
posture (Oracle mode, consensus requirements). Personalities live in
``kintsugi/config/personalities/`` by default; deployments point
``PERSONALITY_DIR`` elsewhere to define their own.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULT_PERSONALITY_DIR = Path(__file__).resolve().parent.parent / "config" / "personalities"


@dataclass
class SafetyConfig:
    """Safety posture for one personality."""

    oracle_mode: str = "observe"  # off | observe | enforce
    max_actions_per_turn: int = 5
    consensus_actions: list[str] = field(default_factory=list)
    # Oracle flag score above which a response is blocked in enforce mode.
    block_threshold: float = 0.8

    def __post_init__(self) -> None:
        if self.oracle_mode not in ("off", "observe", "enforce"):
            raise ValueError(f"oracle_mode must be off/observe/enforce, got {self.oracle_mode!r}")
        if not 0.0 <= self.block_threshold <= 1.0:
            raise ValueError("block_threshold must be in [0, 1]")


@dataclass
class AgentPersonality:
    """Declarative configuration for one agent archetype."""

    name: str
    display_name: str = ""
    description: str = ""
    system_prompt: str = ""
    # Cognition EFE weights: risk / ambiguity / epistemic, sum ~1.0
    efe_weights: dict[str, float] = field(
        default_factory=lambda: {"risk": 0.33, "ambiguity": 0.34, "epistemic": 0.33}
    )
    model_tier: str = "sonnet"  # haiku | sonnet | opus
    skills_allow: list[str] = field(default_factory=lambda: ["*"])
    skills_deny: list[str] = field(default_factory=list)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_path: str | None = None

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.name.replace("_", " ").replace("-", " ").title()
        total = sum(self.efe_weights.get(k, 0.0) for k in ("risk", "ambiguity", "epistemic"))
        if abs(total - 1.0) > 0.05:
            raise ValueError(
                f"personality {self.name!r}: EFE weights must sum to ~1.0 (got {total:.3f})"
            )

    def allows_skill(self, skill_name: str) -> bool:
        """Deny patterns win over allow patterns."""
        if any(fnmatch(skill_name, pattern) for pattern in self.skills_deny):
            return False
        return any(fnmatch(skill_name, pattern) for pattern in self.skills_allow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "efe_weights": self.efe_weights,
            "model_tier": self.model_tier,
            "skills": {"allow": self.skills_allow, "deny": self.skills_deny},
            "safety": {
                "oracle_mode": self.safety.oracle_mode,
                "max_actions_per_turn": self.safety.max_actions_per_turn,
                "consensus_actions": self.safety.consensus_actions,
                "block_threshold": self.safety.block_threshold,
            },
            "metadata": self.metadata,
            "source_path": self.source_path,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any], source_path: str | None = None) -> AgentPersonality:
        skills = raw.get("skills", {}) or {}
        safety_raw = raw.get("safety", {}) or {}
        return cls(
            name=raw["name"],
            display_name=raw.get("display_name", ""),
            description=raw.get("description", ""),
            system_prompt=raw.get("system_prompt", ""),
            efe_weights=raw.get(
                "efe_weights", {"risk": 0.33, "ambiguity": 0.34, "epistemic": 0.33}
            ),
            model_tier=raw.get("model_tier", "sonnet"),
            skills_allow=list(skills.get("allow", ["*"])),
            skills_deny=list(skills.get("deny", [])),
            safety=SafetyConfig(
                oracle_mode=safety_raw.get("oracle_mode", "observe"),
                max_actions_per_turn=int(safety_raw.get("max_actions_per_turn", 5)),
                consensus_actions=list(safety_raw.get("consensus_actions", [])),
                block_threshold=float(safety_raw.get("block_threshold", 0.8)),
            ),
            metadata=raw.get("metadata", {}) or {},
            source_path=source_path,
        )


def load_personality_file(path: Path) -> AgentPersonality:
    """Load a single personality from a .yaml/.yml/.toml file."""
    if path.suffix in (".yaml", ".yml"):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    elif path.suffix == ".toml":
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"unsupported personality format: {path.suffix}")
    if not isinstance(raw, dict):
        raise ValueError(f"personality file {path} must contain a mapping")
    raw.setdefault("name", path.stem)
    return AgentPersonality.from_dict(raw, source_path=str(path))


class PersonalityRegistry:
    """Loads and caches personalities from a directory."""

    def __init__(self, directory: Path | str | None = None) -> None:
        self.directory = Path(directory) if directory else DEFAULT_PERSONALITY_DIR
        self._personalities: dict[str, AgentPersonality] = {}
        self.reload()

    def reload(self) -> list[str]:
        """Re-scan the personality directory. Returns loaded names."""
        loaded: dict[str, AgentPersonality] = {}
        if self.directory.is_dir():
            for path in sorted(self.directory.iterdir()):
                if path.suffix not in (".yaml", ".yml", ".toml"):
                    continue
                try:
                    personality = load_personality_file(path)
                    loaded[personality.name] = personality
                except Exception as exc:
                    logger.warning("skipping personality %s: %s", path, exc)
        if "default" not in loaded:
            loaded["default"] = AgentPersonality(
                name="default", description="Built-in fallback personality"
            )
        self._personalities = loaded
        return sorted(loaded)

    def get(self, name: str) -> AgentPersonality:
        try:
            return self._personalities[name]
        except KeyError:
            raise KeyError(
                f"unknown personality {name!r}; available: {sorted(self._personalities)}"
            ) from None

    def list(self) -> list[AgentPersonality]:
        return [self._personalities[k] for k in sorted(self._personalities)]

    def __contains__(self, name: str) -> bool:
        return name in self._personalities


_registry: PersonalityRegistry | None = None


def get_personality_registry() -> PersonalityRegistry:
    """Global personality registry, honoring settings.PERSONALITY_DIR."""
    global _registry
    if _registry is None:
        directory: Path | None = None
        try:
            from kintsugi.config.settings import settings

            if settings.PERSONALITY_DIR:
                directory = Path(settings.PERSONALITY_DIR)
        except Exception:  # pragma: no cover - settings import failure
            pass
        _registry = PersonalityRegistry(directory)
    return _registry

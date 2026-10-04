"""Domain Packs: optional YAML hints per industry (typical roles, entities, critical rules, edge cases).

The engine never depends on a pack existing. Packs sharpen tests and feed the offline heuristic classifier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import yaml

from app.core.paths import DOMAIN_PACKS_DIR


@dataclass
class DomainPack:
    name: str
    label: str
    sub_types: list[str] = field(default_factory=list)
    keywords: dict[str, float] = field(default_factory=dict)
    typical_roles: list[str] = field(default_factory=list)
    typical_entities: list[str] = field(default_factory=list)
    typical_features: list[str] = field(default_factory=list)
    critical_rules: list[str] = field(default_factory=list)
    edge_cases: list[str] = field(default_factory=list)
    priority_hints: dict[str, list[str]] = field(default_factory=dict)
    privacy_blur: bool = False

    def prompt_hint(self) -> str:
        return (
            f"Domain pack '{self.name}' ({self.label}). Typical entities: {', '.join(self.typical_entities)}. "
            f"Critical rules to look for: {'; '.join(self.critical_rules)}. "
            f"Edge cases: {'; '.join(self.edge_cases)}."
        )


@lru_cache(maxsize=1)
def load_packs() -> dict[str, DomainPack]:
    packs: dict[str, DomainPack] = {}
    for path in sorted(DOMAIN_PACKS_DIR.glob("*.yaml")):
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        known = {k: v for k, v in data.items() if k in DomainPack.__dataclass_fields__}
        pack = DomainPack(**known)
        packs[pack.name] = pack
    return packs


def get_pack(domain: str) -> DomainPack | None:
    return load_packs().get(domain)


KNOWN_DOMAINS = [
    "healthcare",
    "rental",
    "ecommerce",
    "education",
    "hr",
    "crm",
    "restaurant",
    "real_estate",
    "banking",
    "booking",
    "portfolio",
    "blog",
    "other",
]

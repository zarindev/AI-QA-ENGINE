"""Domain-aware fake test data. Never real personal data.

* Names and free text carry the `QAP_` prefix so records created by tests are easy to find and clean up.
* Emails use the reserved `example.test` domain; phone numbers use the fictional 555-01xx range.
* Values are deterministic per seed, so a regenerated suite does not churn.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from faker import Faker

from app.storage.schemas import Element

_MEDICATIONS = ["Amoxicillin", "Ibuprofen", "Metformin", "Lisinopril", "Cetirizine", "Omeprazole"]


@dataclass
class Probe:
    """One value to try in a field, and whether the app should accept it."""

    label: str
    value: str
    valid: bool


def _num(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


class TestDataFactory:
    __test__ = False  # not a pytest class

    def __init__(self, seed: int = 2026, today: date | None = None) -> None:
        self.fake = Faker()
        self.fake.seed_instance(seed)
        self.today = today or date.today()

    # ------------------------------------------------------------------ valid values

    def value_for(self, label: str, field_type: str = "", options: list[str] | None = None) -> str:
        """A realistic, clearly fake, valid value for a field, chosen from its label and HTML type."""
        name = label.lower()
        t = (field_type or "").lower()
        if options:
            real = [
                o
                for o in options
                if o.strip() and not re.match(r"^(select|choose|—|-|all)\b", o.strip(), re.I)
            ]
            return real[0] if real else options[0]
        if t == "email" or "email" in name:
            return f"qap.{self.fake.user_name()}@example.test"
        if t == "tel" or re.search(r"phone|mobile|tel\b", name):
            return f"+1 555 01{self.fake.numerify('##')}"
        if re.search(r"birth|dob", name):
            return (self.today - timedelta(days=365 * 34 + 40)).isoformat()
        if t == "date" or re.search(r"\bdate\b|pickup|return|check.?in|check.?out|due", name):
            return (self.today + timedelta(days=7)).isoformat()
        if t == "time" or re.search(r"\btime\b", name):
            return "10:30"
        if re.search(r"coverage|percent|%|discount|rate %", name):
            return "20"
        if re.search(r"price|fee|cost|rate|amount|salary|total", name):
            return "49.90"
        if re.search(r"qty|quantity|stock|seats|count|days|duration|nights", name):
            return "3"
        if t == "number":
            return "5"
        if re.search(r"\bsku\b|code|plate|reference|ref\b", name):
            return f"QAP-{self.fake.bothify('??-###').upper()}"
        if re.search(r"medication|drug|medicine", name):
            return self.fake.random_element(_MEDICATIONS)
        if re.search(r"dosage|dose", name):
            return "500 mg twice daily"
        if re.search(r"first.?name", name):
            return f"QAP_{self.fake.first_name()}"
        if re.search(r"last.?name|surname", name):
            return f"QAP_{self.fake.last_name()}"
        if re.search(r"name|patient|customer|client|employee|supplier|title|make|model", name):
            return f"QAP_{self.fake.first_name()} {self.fake.last_name()}"
        if re.search(r"address|street", name):
            return f"QAP_{self.fake.building_number()} Test Street"
        if re.search(r"city", name):
            return "QAP_Testville"
        if re.search(r"url|website", name) or t == "url":
            return "https://example.test/qap"
        if t == "password" or "password" in name:
            return "QAP-Passw0rd!"
        if re.search(r"note|comment|description|reason|message", name) or t == "textarea":
            return f"QAP_ test note {self.fake.word()}"
        return f"QAP_{self.fake.word()}"

    def form_values(self, fields: list[Element]) -> dict[str, str]:
        out: dict[str, str] = {}
        for f in fields:
            if f.tag not in ("input", "select", "textarea") or f.type in (
                "submit",
                "button",
                "hidden",
                "checkbox",
                "radio",
            ):
                continue
            label = f.label or f.name or f.placeholder or f"field {f.index}"
            out[label] = self.value_for(label, f.type or f.tag, f.options)
        return out

    # ------------------------------------------------------------------ boundaries & classes

    def boundaries(self, f: Element) -> list[Probe]:
        """Boundary value analysis from the field's own HTML constraints."""
        probes: list[Probe] = []
        lo, hi = _num(f.min), _num(f.max)
        if lo is not None:
            probes += [
                Probe(f"min − 1 ({lo - 1:g})", f"{lo - 1:g}", False),
                Probe(f"min ({lo:g})", f"{lo:g}", True),
            ]
        if hi is not None:
            probes += [
                Probe(f"max ({hi:g})", f"{hi:g}", True),
                Probe(f"max + 1 ({hi + 1:g})", f"{hi + 1:g}", False),
            ]
        if f.maxlength:
            probes += [
                Probe(f"max length ({f.maxlength} chars)", "Q" * f.maxlength, True),
                Probe(f"max length + 1 ({f.maxlength + 1} chars)", "Q" * (f.maxlength + 1), False),
            ]
        if f.minlength:
            probes += [
                Probe(f"min length − 1 ({f.minlength - 1} chars)", "Q" * (f.minlength - 1), False),
                Probe(f"min length ({f.minlength} chars)", "Q" * f.minlength, True),
            ]
        if f.required:
            probes.append(Probe("empty", "", False))
        if lo is not None and lo not in (0, 1):  # min−1 / min already cover zero when min is 0 or 1
            probes.append(Probe("zero", "0", lo <= 0))
        return probes

    def invalid_classes(self, f: Element) -> list[Probe]:
        """Equivalence partitioning: one representative per invalid class the field type implies."""
        label = (f.label or f.name).lower()
        t = f.type
        probes: list[Probe] = []
        if t == "email" or "email" in label:
            probes += [
                Probe("missing @", "qap.user.example.test", False),
                Probe("missing domain", "qap@", False),
            ]
        if t == "number" or re.search(r"price|fee|cost|rate|qty|quantity|stock|days|amount|coverage", label):
            probes += [Probe("negative number", "-5", False), Probe("letters", "abc", False)]
        if re.search(r"phone|mobile|tel", label) or t == "tel":
            probes += [Probe("letters", "call me maybe", False), Probe("too short", "12", False)]
        if re.search(r"birth|dob", label):
            probes += [Probe("date in the future", (self.today + timedelta(days=365)).isoformat(), False)]
        if re.search(r"pickup|return|appointment|booking|check.?in|start|due|delivery|visit", label) and (
            t == "date" or "date" in label
        ):
            probes += [Probe("date in the past", (self.today - timedelta(days=3)).isoformat(), False)]
        return probes

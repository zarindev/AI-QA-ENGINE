"""Stage ② Understand: what kind of application is this, who uses it, and what does it manage?

Primary path: Claude reads the crawl summary plus a few representative screenshots and returns a strict JSON
SiteProfile (domain, sub-type, confidence, roles, modules, features, entities with fields, evidence).
Fallback (no API key): a transparent keyword classifier over the crawl, driven by the Domain Pack keywords,
with entities taken from forms and tables. It is labelled `method: heuristic` and its confidence is capped.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from PIL import Image
from pydantic import BaseModel

from app.core.logging import get_logger
from app.core.paths import PROMPTS_DIR
from app.storage.schemas import (
    CrawlResult,
    Entity,
    EntityField,
    Evidence,
    Feature,
    PageRecord,
    RoleProfile,
    SiteProfile,
)
from app.understand import summary as summ
from app.understand.packs import KNOWN_DOMAINS, load_packs

log = get_logger("understand")

HEURISTIC_MAX_CONFIDENCE = 0.75
Operation = Literal["create", "read", "update", "delete", "list", "search"]


# ---------------------------------------------------------------- AI output schema (strict JSON)


class AIField(BaseModel):
    name: str
    type: str
    required: bool
    validation: str


class AIEntity(BaseModel):
    name: str
    fields: list[AIField]
    relations: list[str]
    pages: list[str]
    operations: list[Literal["create", "read", "update", "delete", "list", "search"]]


class AIFeature(BaseModel):
    name: str
    module: str
    description: str
    roles: list[str]
    pages: list[str]


class AIRole(BaseModel):
    name: str
    description: str


class AIEvidence(BaseModel):
    claim: str
    source: str
    weight: float


class AIClassification(BaseModel):
    domain: Literal[
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
    sub_type: str
    confidence: float
    summary: str
    roles: list[AIRole]
    modules: list[str]
    features: list[AIFeature]
    entities: list[AIEntity]
    evidence: list[AIEvidence]


def _system_prompt() -> str:
    return (PROMPTS_DIR / "understand.md").read_text(encoding="utf-8")


def _screenshot_block(path: Path, max_width: int = 1280) -> dict[str, Any]:
    import base64

    img = Image.open(path).convert("RGB")
    if img.width > max_width:
        img = img.resize((max_width, int(img.height * max_width / img.width)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=72, optimize=True)
    data = base64.standard_b64encode(buf.getvalue()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def representative_pages(crawl: CrawlResult, limit: int = 4) -> list[PageRecord]:
    """Landing page of each role first (dashboards say the most), then the richest form and table screens."""
    chosen: list[PageRecord] = []
    seen_templates: set[str] = set()

    def add(page: PageRecord | None) -> None:
        if page and page.screenshot and page.url_template not in seen_templates and len(chosen) < limit:
            chosen.append(page)
            seen_templates.add(page.url_template)

    for role in [r.role for r in crawl.roles if r.role != "public"] or ["public"]:
        add(next((p for p in crawl.pages if p.role == role and not p.is_login_page), None))
    add(
        max(
            (p for p in crawl.pages if p.forms and not p.is_login_page),
            key=lambda p: len(p.elements),
            default=None,
        )
    )
    add(
        max(
            (p for p in crawl.pages if p.tables),
            key=lambda p: sum(t.row_count for t in p.tables),
            default=None,
        )
    )
    for page in crawl.pages:
        add(page if not page.is_login_page else None)
    return chosen


def classify_with_ai(ai: Any, crawl: CrawlResult, run_dir: Path) -> SiteProfile:
    screens = summ.summarize(crawl)
    text = summ.render(crawl, screens)
    pages = representative_pages(crawl)
    content: list[dict[str, Any]] = []
    for page in pages:
        content.append({"type": "text", "text": f"Screenshot of {page.url_template} as role '{page.role}':"})
        content.append(_screenshot_block(run_dir / page.screenshot))
    packs = load_packs()
    pack_list = "; ".join(f"{p.name} = {p.label}" for p in packs.values())
    content.append({"type": "text", "text": f"Known domains: {pack_list}; other = none of these.\n\n{text}"})
    result = ai.structured(
        system=_system_prompt(),
        content=content,
        schema=AIClassification,
        purpose="classify site",
        effort="medium",
    )
    crawled_roles = {r.role for r in crawl.roles}
    profile = SiteProfile(
        domain=result.domain,
        sub_type=result.sub_type,
        confidence=max(0.0, min(1.0, result.confidence)),
        summary=result.summary,
        method="ai",
        roles=[r.name for r in result.roles],
        role_details=[
            RoleProfile(name=r.name, description=r.description, observed=r.name in crawled_roles)
            for r in result.roles
        ],
        modules=result.modules,
        features=[
            Feature(
                id=f"FT-{i:02d}",
                name=f.name,
                module=f.module,
                description=f.description,
                roles=f.roles,
                pages=f.pages,
            )
            for i, f in enumerate(result.features, 1)
        ],
        entities=[
            Entity(
                name=e.name,
                fields=[EntityField(**fld.model_dump()) for fld in e.fields],
                relations=e.relations,
                pages=e.pages,
                operations=e.operations,
            )
            for e in result.entities
        ],
        evidence=[
            Evidence(claim=e.claim, source=e.source, weight=max(0.0, min(1.0, e.weight)))
            for e in result.evidence
        ],
    )
    _attach_pack(profile)
    return profile


# ---------------------------------------------------------------- heuristic fallback


def _corpus(crawl: CrawlResult) -> list[tuple[str, str]]:
    """(text, source url) pairs from the parts of each page that describe the app rather than its data."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for page in crawl.pages:
        if page.url_template in seen:
            continue
        seen.add(page.url_template)
        bits = [
            page.title,
            page.url_template.replace("/", " ").replace("_", " ").replace("-", " "),
            *page.headings,
        ]
        for e in page.elements:
            if e.tag in ("a", "button", "label", "select") or e.form_index is not None:
                bits.append(e.label or e.text or e.placeholder or e.name)
        for t in page.tables:
            bits.extend(t.headers)
        out.append((" ".join(b for b in bits if b).lower(), page.url))
    return out


def domain_scores(crawl: CrawlResult) -> tuple[dict[str, float], dict[str, list[tuple[str, str]]]]:
    corpus = _corpus(crawl)
    scores: dict[str, float] = {}
    hits: dict[str, list[tuple[str, str]]] = {}
    for name, pack in load_packs().items():
        total = 0.0
        for keyword, weight in pack.keywords.items():
            rx = re.compile(rf"\b{re.escape(keyword)}s?\b")
            count, first_source = 0, ""
            for text, source in corpus:
                n = len(rx.findall(text))
                if n and not first_source:
                    first_source = source
                count += n
            if count:
                total += float(weight) * min(count, 6)
                hits.setdefault(name, []).append((keyword, first_source))
        scores[name] = round(total, 1)
    return scores, hits


_PLURAL = [(re.compile(r"ies$"), "y"), (re.compile(r"(ss|sh|ch|x)es$"), r"\1"), (re.compile(r"s$"), "")]


def singular(word: str) -> str:
    w = word.strip()
    for rx, repl in _PLURAL:
        if rx.search(w.lower()):
            return rx.sub(repl, w)
    return w


_ENTITY_VERBS = re.compile(
    r"^(register|add|new|create|edit|update|book|write|record|receive)\s+(a\s+|an\s+)?", re.I
)


def _entity_name_from(text: str) -> str:
    text = _ENTITY_VERBS.sub("", text.strip())
    text = re.sub(r"\s+(for|to|of)\b.*$", "", text, flags=re.I)
    words = text.split()
    if not words or len(words) > 3 or not re.search(r"[a-z]{3}", text, re.I):
        return ""
    return singular(" ".join(words)).title()


_PLACEHOLDER = re.compile(r"\{(id|uuid|hash|slug|date)\}")
_NOT_ENTITIES = re.compile(r"dashboard|report|overview|summary|analytic|home|welcome|statistic|insight", re.I)
_GENERIC_HEADERS = {
    "#",
    "id",
    "date",
    "name",
    "sku",
    "item",
    "time",
    "status",
    "qty",
    "type",
    "no",
    "code",
    "title",
}


_ACTION_SEGMENTS = {"new", "edit", "create", "add", "view", "detail", "details", "show", "update", "delete"}
_DATE_HEADER = re.compile(r"^(mon|tue|wed|thu|fri|sat|sun)\b|\d{2}", re.I)


def _nice(label: str) -> str:
    """Store labels the way a person writes them: CSS upper-casing ("DATE OF BIRTH") and snake_case names
    (pickup_date, used when a field has no label) become "Date of birth" / "Pickup date"."""
    label = label.strip()
    if re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)+", label):
        label = label.replace("_", " ")
        return label[0].upper() + label[1:]
    return label.capitalize() if label.isupper() and len(label) > 1 else label


def _entity_from_template(template: str) -> str:
    """/patients/{id}/edit -> Patient: on record pages the URL names the entity, the heading names the record."""
    parts = [p for p in template.split("?")[0].split("/") if p]
    for i, part in enumerate(parts):
        if _PLACEHOLDER.fullmatch(part) and i > 0:
            return singular(parts[i - 1].replace("-", " ").replace("_", " ")).title()
    query = template.split("?")[1] if "?" in template else ""
    if _PLACEHOLDER.search(query) and parts:
        nouns = [p for p in parts if p.lower() not in _ACTION_SEGMENTS]
        if nouns:
            return singular(re.sub(r"[-_]|\.html?$", " ", nouns[-1]).strip()).title()
    return ""


def _page_entity(page: PageRecord, heading: str) -> str:
    if _PLACEHOLDER.search(page.url_template):
        return _entity_from_template(page.url_template)
    return _entity_name_from(heading)


def _entities(crawl: CrawlResult) -> list[Entity]:
    entities: dict[str, Entity] = {}
    for page in crawl.pages:
        if page.is_login_page:
            continue
        for form in page.forms:
            if form.purpose not in ("create", "edit", "other") or len(form.field_indices) < 2:
                continue
            name = _page_entity(page, form.heading or (page.headings[0] if page.headings else page.title))
            if not name or _NOT_ENTITIES.search(name):
                continue
            ent = entities.setdefault(name, Entity(name=name))
            if page.url_template not in ent.pages:
                ent.pages.append(page.url_template)
            op: Operation = "update" if form.purpose == "edit" or "edit" in page.url_template else "create"
            if op not in ent.operations:
                ent.operations.append(op)
            known = {f.name.lower() for f in ent.fields}
            for idx in form.field_indices:
                e = next((x for x in page.elements if x.index == idx), None)
                if (
                    e is None
                    or e.tag not in ("input", "select", "textarea")
                    or e.type in ("submit", "button", "hidden")
                ):
                    continue
                label = _nice(re.sub(r"\s*\(.*?\)\s*$", "", (e.label or e.name or e.placeholder)))
                if not label or label.lower() in known:
                    continue
                known.add(label.lower())
                rules = [f"{k}={v}" for k, v in (("min", e.min), ("max", e.max), ("pattern", e.pattern)) if v]
                if e.maxlength:
                    rules.append(f"maxlength={e.maxlength}")
                if e.options:
                    rules.append("one of: " + ", ".join(e.options[:8]))
                ent.fields.append(
                    EntityField(
                        name=label, type=e.type or e.tag, required=e.required, validation="; ".join(rules)
                    )
                )
        heading = page.headings[0] if page.headings else page.title
        if _NOT_ENTITIES.search(heading) or _NOT_ENTITIES.search(page.url_template):
            continue
        for table in page.tables:
            if not table.headers:
                continue
            first = table.headers[0].strip().lower()
            # "Invoice | Date | Patient…" on a page called Billing: the first column names the record.
            # On a record page (/cars/{id}) a table lists *related* records, so only the first column can name it.
            if first not in _GENERIC_HEADERS and len(first.split()) == 1:
                name = singular(first).title()
            elif _PLACEHOLDER.search(page.url_template):
                continue
            else:
                name = _page_entity(page, heading)
            if not name or _NOT_ENTITIES.search(name):
                continue
            ent = entities.setdefault(name, Entity(name=name))
            if page.url_template not in ent.pages:
                ent.pages.append(page.url_template)
            for view_op in ("list", "read"):
                if view_op not in ent.operations:
                    ent.operations.append(view_op)  # type: ignore[arg-type]
            known = {f.name.lower() for f in ent.fields}
            for header in table.headers:
                header = _nice(header)
                if header.lower() == name.lower() or _DATE_HEADER.search(header):
                    continue  # the record's own id column, or calendar day columns
                if header and header.lower() not in known and len(header) < 40 and header != "#":
                    known.add(header.lower())
                    ent.fields.append(EntityField(name=header, type="text"))
    # relations: a field named after another entity ("Doctor" on Appointment)
    names = {n.lower(): n for n in entities}
    for ent in entities.values():
        for fld in ent.fields:
            other = names.get(singular(fld.name).lower())
            if other and other != ent.name and other not in ent.relations:
                ent.relations.append(other)
    return [e for e in entities.values() if len(e.fields) >= 2]


def classify_heuristic(crawl: CrawlResult) -> SiteProfile:
    scores, hits = domain_scores(crawl)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_name, top = ranked[0] if ranked else ("other", 0.0)
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    distinct = len(hits.get(top_name, []))
    if top < 12 or distinct < 4:
        # A handful of generic words ("table", "menu") is not a domain; say so instead of guessing.
        domain, confidence = "other", 0.2
    else:
        margin = (top - second) / top
        domain, confidence = top_name, round(min(HEURISTIC_MAX_CONFIDENCE, 0.3 + 0.6 * margin), 2)
    pack = load_packs().get(domain)
    nav = summ.navigation_labels(crawl)
    modules: list[str] = []
    for labels in nav.values():
        for label in labels:
            if label not in modules and label.lower() not in ("log out", "logout", "help", "home"):
                modules.append(label)
    roles = [r.role for r in crawl.roles if r.role != "public"]
    features = [
        Feature(
            id=f"FT-{i:02d}",
            name=m,
            module=m,
            roles=[r for r, labels in nav.items() if m in labels and r != "public"],
        )
        for i, m in enumerate(modules, 1)
    ]
    evidence = [
        Evidence(claim=f"Keyword “{kw}” appears in the app's screens", source=src, weight=0.5)
        for kw, src in hits.get(domain, [])[:8]
    ]
    evidence.append(
        Evidence(
            claim=f"Keyword score {top} for {top_name} vs {second} for the runner-up",
            source="heuristic classifier",
            weight=0.3,
        )
    )
    entities = _entities(crawl)
    summary = (
        f"Looks like a {pack.label.lower() + ' application' if pack else 'web application'} with "
        f"{len(entities)} managed record types and {len(roles) or 'no'} signed-in roles. "
        "Classified offline from keywords; add an Anthropic API key for a full AI analysis."
    )
    profile = SiteProfile(
        domain=domain,
        sub_type=(pack.sub_types[0] if pack and pack.sub_types else ""),
        confidence=confidence,
        summary=summary,
        method="heuristic",
        domain_scores=dict(ranked[:5]),
        roles=roles,
        role_details=[RoleProfile(name=r, observed=True) for r in roles],
        modules=modules,
        features=features,
        entities=entities,
        evidence=evidence,
    )
    _attach_pack(profile)
    return profile


def _attach_pack(profile: SiteProfile) -> None:
    if profile.domain in load_packs():
        profile.domain_pack = profile.domain
    if profile.domain not in KNOWN_DOMAINS:
        profile.domain = "other"


def most_common_words(crawl: CrawlResult, n: int = 20) -> list[str]:
    """Debug helper: frequent words in the classifier corpus."""
    words: Counter[str] = Counter()
    for text, _ in _corpus(crawl):
        words.update(w for w in re.findall(r"[a-z]{4,}", text))
    return [w for w, _ in words.most_common(n)]

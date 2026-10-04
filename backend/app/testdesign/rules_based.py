"""Deterministic test design from what the crawl actually saw (no AI, no cost).

Techniques: smoke (every page per role), form validation (required fields), boundary value analysis and
equivalence partitioning (from each field's HTML constraints and type), CRUD create, role permission (direct-URL
access to screens a role never reached), unauthenticated access, UI/responsive and accessibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.storage.schemas import (
    CrawlResult,
    Element,
    Form,
    PageRecord,
    SiteProfile,
    Technique,
    TestCase,
    TestStep,
)
from app.testdesign.testdata import Probe, TestDataFactory

_SKIP_FIELD_TYPES = ("submit", "button", "hidden", "checkbox", "radio", "image", "reset")


@dataclass
class Draft:
    """A test case before it gets an id. `module` is used for the TC-<MOD>-NNN code."""

    case: TestCase
    module: str
    key: str  # de-duplication key
    extra: dict = field(default_factory=dict)


def _fields(page: PageRecord, form: Form) -> list[Element]:
    by_index = {e.index: e for e in page.elements}
    return [
        by_index[i]
        for i in form.field_indices
        if i in by_index
        and by_index[i].tag in ("input", "select", "textarea")
        and by_index[i].type not in _SKIP_FIELD_TYPES
    ]


def _label(e: Element) -> str:
    return (e.label or e.name or e.placeholder or f"field {e.index}").strip()


def _module_for(profile: SiteProfile, template: str, fallback: str) -> str:
    for e in profile.entities:
        if template in e.pages:
            return e.name
    parts = [p for p in template.split("?")[0].split("/") if p and not p.startswith("{")]
    return parts[0].replace("-", " ").replace("_", " ").title() if parts else fallback


def _usable(page: PageRecord) -> bool:
    return not page.is_login_page and (page.status_code or 200) < 400


_PLACEHOLDER = re.compile(r"\{(id|uuid|hash|slug|date)\}")


def _short_title(title: str) -> str:
    return re.split(r"\s+[·|–—-]\s+", title)[0].strip() if title else ""


def form_name(page: PageRecord, form: Form, template_titles: set[str] | None = None) -> str:
    """Human name for a form, without record data in it.

    On record pages (/products/{id}/edit) headings and titles often name the *record* ("Edit Sparkling Water",
    "Prescription for <patient>"). The title is trusted only when different records of the template share it;
    otherwise the name is built from the URL: "<action> <entity>".
    """
    title = _short_title(page.title)
    if not _PLACEHOLDER.search(page.url_template):
        return form.heading or title or page.url_template
    titles = template_titles or set()
    if len(titles) > 1 and len({_short_title(t) for t in titles}) == 1 and title:
        return title
    parts = [p for p in page.url_template.split("?")[0].split("/") if p]
    nouns = [p for p in parts if not _PLACEHOLDER.fullmatch(p)]
    if len(nouns) >= 2:
        entity = re.sub(r"[-_]", " ", nouns[0])
        entity = entity[:-1] if entity.endswith("s") else entity
        return f"{re.sub(r'[-_]', ' ', nouns[-1]).capitalize()} {entity}"
    return f"{(nouns[0] if nouns else 'Record').capitalize()} details"


def _step(n: int, action: str, data: str = "", expected: str = "") -> TestStep:
    return TestStep(order=n, action=action, data=data, expected=expected)


class RulesBasedDesigner:
    def __init__(self, crawl: CrawlResult, profile: SiteProfile, data: TestDataFactory | None = None) -> None:
        self.crawl = crawl
        self.profile = profile
        self.data = data or TestDataFactory()
        self.logged_in_roles = [r.role for r in crawl.roles if r.role != "public" and r.login_ok]
        self.pages_by_role: dict[str, dict[str, PageRecord]] = {}
        # titles seen per URL template (several records), to tell screen titles from record titles
        self.template_titles: dict[str, set[str]] = {}
        for p in crawl.pages:
            self.template_titles.setdefault(p.url_template, set()).add(p.title)
            if _usable(p):
                self.pages_by_role.setdefault(p.role, {}).setdefault(p.url_template, p)

    def all(self) -> list[Draft]:
        return [
            *self.smoke(),
            *self.forms(),
            *self.permissions(),
            *self.unauthenticated(),
            *self.ui(),
            *self.a11y(),
        ]

    # ------------------------------------------------------------------ smoke

    def smoke(self) -> list[Draft]:
        out = []
        for role, pages in self.pages_by_role.items():
            steps = [
                _step(1, f"Log in as {role}" if role != "public" else "Open the site without logging in")
            ]
            for template, page in sorted(pages.items()):
                steps.append(
                    _step(
                        len(steps) + 1,
                        f"Open {template}",
                        page.url,
                        "Page loads (HTTP 2xx), no error text, no JavaScript errors in the console",
                    )
                )
            out.append(
                Draft(
                    TestCase(
                        id="",
                        title=f"Every screen loads for {role}",
                        technique="smoke",
                        type="functional",
                        priority="P2",
                        role=role,
                        steps=steps,
                        expected_result=f"All {len(pages)} screens reachable by {role} load without errors.",
                        links={"pages": sorted(pages)},
                    ),
                    module="Smoke",
                    key=f"smoke:{role}",
                )
            )
        return out

    # ------------------------------------------------------------------ forms

    def forms(self) -> list[Draft]:
        out: list[Draft] = []
        seen: set[str] = set()
        for role, pages in self.pages_by_role.items():
            if role == "public":
                continue
            for template, page in pages.items():
                for form in page.forms:
                    fields = _fields(page, form)
                    if (
                        form.purpose not in ("create", "edit", "other")
                        or len(fields) < 2
                        or form.submit_index is None
                    ):
                        continue
                    key = f"{template}#{form.index}"
                    if key in seen:
                        continue
                    seen.add(key)
                    out += self._form_cases(role, page, form, fields)
        return out

    def _form_cases(self, role: str, page: PageRecord, form: Form, fields: list[Element]) -> list[Draft]:
        module = _module_for(self.profile, page.url_template, "Forms")
        name = form_name(page, form, self.template_titles.get(page.url_template))
        submit = next((e for e in page.elements if e.index == form.submit_index), None)
        submit_label = _label(submit) if submit else "Submit"
        valid = self.data.form_values(fields)
        fill_valid = [
            _step(1, f"Log in as {role} and open {page.url_template}", page.url),
            *[_step(i + 2, f"Enter “{label}”", value) for i, (label, value) in enumerate(valid.items())],
        ]
        base_links = {"pages": [page.url_template]}
        out: list[Draft] = []

        # CRUD create — the positive path
        out.append(
            Draft(
                TestCase(
                    id="",
                    title=f"{name}: save with valid data",
                    technique="crud",
                    type="functional",
                    priority="P2",
                    role=role,
                    test_data=valid,
                    steps=[
                        *fill_valid,
                        _step(
                            len(fill_valid) + 1,
                            f"Click “{submit_label}”",
                            "",
                            "Saved; a success message is shown",
                        ),
                    ],
                    expected_result=f"The record is saved and appears in the {module} list with the entered values.",
                    links=base_links,
                    requires_full_mode=True,
                ),
                module,
                key=f"crud:{page.url_template}#{form.index}",
            )
        )

        # Validation — required fields left empty
        required = [f for f in fields if f.required]
        if required:
            out.append(
                Draft(
                    TestCase(
                        id="",
                        title=f"{name}: required fields are enforced",
                        technique="validation",
                        type="negative",
                        priority="P3",
                        role=role,
                        steps=[
                            _step(1, f"Log in as {role} and open {page.url_template}", page.url),
                            _step(2, "Leave every field empty"),
                            _step(
                                3,
                                f"Click “{submit_label}”",
                                "",
                                "Nothing is saved; each required field shows an error: "
                                + ", ".join(_label(f) for f in required),
                            ),
                        ],
                        expected_result="The form is rejected until all required fields are filled.",
                        links=base_links,
                        requires_full_mode=True,
                    ),
                    module,
                    key=f"required:{page.url_template}#{form.index}",
                )
            )

        # Boundary values and equivalence classes, one case per field
        for f in fields:
            label = _label(f)
            others = {k: v for k, v in valid.items() if k != label}
            checks: list[tuple[Technique, list[Probe]]] = [
                ("boundary", self.data.boundaries(f)),
                ("equivalence", self.data.invalid_classes(f)),
            ]
            for technique, probes in checks:
                probes = [p for p in probes if not (technique == "boundary" and p.label == "empty")]
                if not probes:
                    continue
                steps = [
                    _step(1, f"Log in as {role} and open {page.url_template}", page.url),
                    _step(
                        2,
                        "Fill the other fields with valid data",
                        "; ".join(f"{k} = {v}" for k, v in others.items()),
                    ),
                ]
                for p in probes:
                    outcome = "accepted and saved" if p.valid else "rejected with a clear validation message"
                    steps.append(
                        _step(
                            len(steps) + 1,
                            f"Enter {p.label} in “{label}” and click “{submit_label}”",
                            p.value,
                            f"Value is {outcome}",
                        )
                    )
                title = (
                    f"{name}: “{label}” boundaries"
                    if technique == "boundary"
                    else f"{name}: “{label}” rejects invalid input"
                )
                out.append(
                    Draft(
                        TestCase(
                            id="",
                            title=title,
                            technique=technique,
                            type="negative",
                            priority="P3",
                            role=role,
                            test_data={
                                "field": label,
                                "probes": [p.__dict__ for p in probes],
                                "other_fields": others,
                            },
                            steps=steps,
                            expected_result="Valid values are accepted; invalid values are rejected without saving.",
                            links=base_links,
                            requires_full_mode=True,
                        ),
                        module,
                        key=f"{technique}:{page.url_template}#{form.index}:{label}",
                    )
                )
        return out

    # ------------------------------------------------------------------ permissions

    def permissions(self) -> list[Draft]:
        """A screen some role reached but another logged-in role never saw: opening it by URL should be refused."""
        out = []
        reached = {role: set(pages) for role, pages in self.pages_by_role.items()}
        all_pages: dict[str, PageRecord] = {}
        for role in self.logged_in_roles:
            for template, page in self.pages_by_role.get(role, {}).items():
                all_pages.setdefault(template, page)
        public = reached.get("public", set())
        for role in self.logged_in_roles:
            for template, page in sorted(all_pages.items()):
                if template in reached.get(role, set()) or template in public:
                    continue
                owners = sorted(r for r in self.logged_in_roles if template in reached.get(r, set()))
                module = _module_for(self.profile, template, "Access")
                out.append(
                    Draft(
                        TestCase(
                            id="",
                            title=f"{role.capitalize()} cannot open {template} by direct URL",
                            technique="permission",
                            type="security",
                            priority="P1",
                            role=role,
                            preconditions=[
                                f"{template} is only reachable from the menus of: {', '.join(owners)}"
                            ],
                            steps=[
                                _step(1, f"Log in as {role}"),
                                _step(
                                    2,
                                    f"Type the URL of {template} into the address bar",
                                    page.url,
                                    "Access is refused (403 / redirect to login or dashboard); no data from the page is shown",
                                ),
                            ],
                            expected_result=f"{role} cannot see or use {template}.",
                            links={"pages": [template]},
                        ),
                        module,
                        key=f"perm:{role}:{template}",
                    )
                )
        return out

    def unauthenticated(self) -> list[Draft]:
        public = set(self.pages_by_role.get("public", {}))
        protected: dict[str, PageRecord] = {}
        for role in self.logged_in_roles:
            for template, page in self.pages_by_role.get(role, {}).items():
                if template not in public:
                    protected.setdefault(template, page)
        if not protected:
            return []
        steps = [_step(1, "Open a new browser session without logging in")]
        for template, page in sorted(protected.items()):
            steps.append(
                _step(
                    len(steps) + 1,
                    f"Open {template} directly",
                    page.url,
                    "Redirected to the login page; no protected data is shown",
                )
            )
        return [
            Draft(
                TestCase(
                    id="",
                    title="Signed-out visitors cannot open protected screens",
                    technique="permission",
                    type="security",
                    priority="P1",
                    role="public",
                    steps=steps,
                    expected_result=f"All {len(protected)} protected screens require a login.",
                    links={"pages": sorted(protected)},
                ),
                "Access",
                key="perm:public",
            )
        ]

    # ------------------------------------------------------------------ UI and accessibility

    def ui(self) -> list[Draft]:
        out = []
        for role, pages in self.pages_by_role.items():
            steps = [_step(1, f"Log in as {role}" if role != "public" else "Open the site")]
            for template, page in sorted(pages.items()):
                steps.append(
                    _step(
                        len(steps) + 1,
                        f"Open {template} at 768px and 390px wide",
                        page.url,
                        "No horizontal scrolling, no overlapping or cut-off content, navigation usable",
                    )
                )
            out.append(
                Draft(
                    TestCase(
                        id="",
                        title=f"Screens adapt to tablet and phone for {role}",
                        technique="ui_responsive",
                        type="ui",
                        priority="P4",
                        role=role,
                        steps=steps,
                        viewports=["tablet", "mobile"],
                        expected_result="Every screen is usable at 768px and 390px.",
                        links={"pages": sorted(pages)},
                    ),
                    "UI",
                    key=f"ui:{role}",
                )
            )
        return out

    def a11y(self) -> list[Draft]:
        out = []
        for role, pages in self.pages_by_role.items():
            steps = [_step(1, f"Log in as {role}" if role != "public" else "Open the site")]
            for template, page in sorted(pages.items()):
                steps.append(
                    _step(
                        len(steps) + 1,
                        f"Run an axe-core scan on {template}",
                        page.url,
                        "No critical or serious violations (labels, alt text, contrast, names)",
                    )
                )
            out.append(
                Draft(
                    TestCase(
                        id="",
                        title=f"Accessibility scan of {role} screens",
                        technique="accessibility",
                        type="accessibility",
                        priority="P3",
                        role=role,
                        steps=steps,
                        expected_result="No critical or serious WCAG violations.",
                        links={"pages": sorted(pages)},
                    ),
                    "Accessibility",
                    key=f"a11y:{role}",
                )
            )
        return out

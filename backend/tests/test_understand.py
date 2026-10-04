from __future__ import annotations

from app.storage.schemas import CrawlResult, Element, Form, PageRecord, RoleCrawlSummary, Table
from app.understand import model_builder
from app.understand.classifier import (
    AIClassification,
    _entity_from_template,
    _nice,
    classify_heuristic,
    representative_pages,
    singular,
)
from app.understand.packs import KNOWN_DOMAINS, load_packs
from app.understand.summary import navigation_labels, render, summarize


def _el(i, tag, label="", **kw):
    return Element(index=i, tag=tag, label=label, **kw)


def _crawl() -> CrawlResult:
    nav = [
        _el(0, "a", "Dashboard", href="/"),
        _el(1, "a", "Patients", href="/patients"),
        _el(2, "a", "Appointments", href="/appointments"),
        _el(3, "a", "CarePoint", href="/"),
    ]
    pages = [
        PageRecord(
            id="PG-1",
            role="public",
            url="http://c.test/login",
            url_template="/login",
            title="Sign in",
            is_login_page=True,
            elements=[_el(0, "input", "Email", type="email")],
        ),
        PageRecord(
            id="PG-2",
            role="doctor",
            url="http://c.test/",
            url_template="/",
            title="Dashboard",
            headings=["Dashboard"],
            elements=nav,
            screenshot="a.png",
            tables=[Table(headers=["DATE", "PATIENT", "DOCTOR"], row_count=3)],
        ),
        PageRecord(
            id="PG-3",
            role="doctor",
            url="http://c.test/patients",
            url_template="/patients",
            title="Patients",
            headings=["Patients"],
            elements=nav,
            screenshot="b.png",
            links=["http://c.test/patients/new"],
            tables=[Table(headers=["ID", "NAME", "DATE OF BIRTH", "PHONE", "INSURANCE"], row_count=8)],
        ),
        PageRecord(
            id="PG-4",
            role="doctor",
            url="http://c.test/patients/new",
            url_template="/patients/new",
            title="Register patient",
            headings=["Register patient"],
            screenshot="c.png",
            elements=nav
            + [
                _el(10, "input", "Full name", form_index=0, required=True, maxlength=40),
                _el(11, "input", "Date of birth", type="date", form_index=0, required=True),
                _el(12, "select", "Doctor", form_index=0, options=["Dr. Lee", "Dr. Ray"]),
                _el(13, "button", "Save patient", type="submit", form_index=0),
            ],
            forms=[
                Form(
                    index=0,
                    purpose="create",
                    field_indices=[10, 11, 12, 13],
                    submit_index=13,
                    heading="Register patient",
                )
            ],
        ),
        PageRecord(
            id="PG-5",
            role="doctor",
            url="http://c.test/appointments",
            url_template="/appointments",
            title="Appointments",
            headings=["Appointments"],
            elements=nav,
            screenshot="d.png",
            tables=[Table(headers=["#", "DATE", "PATIENT", "DOCTOR", "STATUS"], row_count=10)],
        ),
        PageRecord(
            id="PG-6",
            role="doctor",
            url="http://c.test/patients/3",
            url_template="/patients/{id}",
            title="Chen Wei",
            headings=["Chen Wei"],
            elements=nav,
            screenshot="e.png",
            tables=[Table(headers=["DATE", "MEDICATION", "DOSAGE"], row_count=1)],
        ),
    ]
    for p in pages:
        p.text_excerpt = "prescription clinic medical appointment"
    return CrawlResult(
        start_url="http://c.test/",
        pages=pages,
        roles=[RoleCrawlSummary(role="public"), RoleCrawlSummary(role="doctor", login_ok=True)],
    )


def test_packs_cover_the_required_domains():
    packs = load_packs()
    assert set(KNOWN_DOMAINS) - {"other"} == set(packs)
    for pack in packs.values():
        assert pack.keywords and pack.critical_rules and pack.typical_entities
    assert packs["healthcare"].privacy_blur and packs["banking"].privacy_blur


def test_text_helpers():
    assert (
        singular("Patients") == "Patient"
        and singular("Categories") == "Category"
        and singular("Boxes") == "Box"
    )
    assert _nice("DATE OF BIRTH") == "Date of birth" and _nice("pickup_date") == "Pickup date"
    assert _entity_from_template("/patients/{id}/edit") == "Patient"
    assert _entity_from_template("/bookings/new?car={id}") == "Booking"
    assert _entity_from_template("/inventory-item.html?id={id}") == "Inventory Item"


def test_summary_and_navigation():
    crawl = _crawl()
    nav = navigation_labels(crawl)["doctor"]
    assert "Patients" in nav and "Dashboard" in nav and "CarePoint" not in nav  # logo and Dashboard share "/"
    screens = summarize(crawl)
    text = render(crawl, screens)
    assert "## /patients/new" in text and "Full name(input, required, maxlength=40)" in text
    assert "Doctor(select, options=Dr. Lee|Dr. Ray) submit: Save patient" in text


def test_heuristic_classifier_on_synthetic_clinic():
    profile = classify_heuristic(_crawl())
    assert profile.method == "heuristic" and profile.domain == "healthcare"
    assert 0 < profile.confidence <= 0.75 and profile.domain_pack == "healthcare"
    names = {e.name for e in profile.entities}
    assert {"Patient", "Appointment"} <= names
    assert (
        "Chen Wei" not in names and "Dashboard" not in names
    )  # record pages and dashboards are not entities
    patient = next(e for e in profile.entities if e.name == "Patient")
    fields = {f.name: f for f in patient.fields}
    assert fields["Full name"].required and "maxlength=40" in fields["Full name"].validation
    assert "Date of birth" in fields and "create" in patient.operations
    assert profile.roles == ["doctor"] and "Patients" in profile.modules


def test_representative_pages_prefer_landing_pages():
    picks = representative_pages(_crawl(), limit=3)
    assert picks[0].id == "PG-2" and len({p.url_template for p in picks}) == 3


def test_model_graph_roundtrip_and_react_flow():
    crawl = _crawl()
    profile = classify_heuristic(crawl)
    g = model_builder.build_model(crawl, profile)
    assert g.nodes["role:doctor"]["kind"] == "role"
    assert g.has_edge("role:doctor", "page:/patients")
    assert any(d.get("kind") == "creates" for _, _, d in g.in_edges("entity:Patient", data=True))
    data = model_builder.to_json(g)
    again = model_builder.from_json(data)
    assert again.number_of_nodes() == g.number_of_nodes() and again.number_of_edges() == g.number_of_edges()
    flow = model_builder.to_react_flow(again, ["role", "page", "entity"])
    kinds = {n["type"] for n in flow["nodes"]}
    assert kinds == {"role", "page", "entity"}
    ids = {n["id"] for n in flow["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in flow["edges"])
    xs = {n["type"]: n["position"]["x"] for n in flow["nodes"]}
    assert xs["role"] < xs["page"] < xs["entity"]


def test_ai_schema_is_strict_json_friendly():
    schema = AIClassification.model_json_schema()
    assert set(schema["required"]) >= {"domain", "confidence", "entities", "evidence"}
    assert "other" in schema["properties"]["domain"]["enum"]

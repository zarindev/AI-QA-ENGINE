"""The demo apps are QA Pilot's benchmark targets: their correct behaviour *and* their planted bugs must stay put.

These tests read the demo apps' source behaviour through Flask's test client only. The QA Pilot engine itself never
reads demo_targets/manifests — only scripts/benchmark.py and this test do.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parents[2] / "demo_targets"
TODAY = date.today()


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"demo_{name}", DEMO / f"{name}_app" / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.store.reset()
    return module


@pytest.fixture
def demo(tmp_path, monkeypatch):
    monkeypatch.setenv("QAP_DEMO_LIVE_DIR", str(tmp_path / "demo-live"))

    return _load


def login(client, email, password):
    client.get("/logout")
    r = client.post("/login", data={"email": email, "password": password})
    assert r.status_code == 302, f"login failed for {email}"


def d(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


@pytest.mark.parametrize("name", ["clinic", "car_rental", "shop_admin"])
def test_manifests_have_12_to_15_bugs_across_categories(name):
    doc = json.loads((DEMO / "manifests" / f"{name}_planted_bugs.json").read_text())
    assert 12 <= len(doc["bugs"]) <= 15
    assert len({b["category"] for b in doc["bugs"]}) >= 8
    source = "".join(p.read_text() for p in (DEMO / f"{name}_app").rglob("*") if p.suffix in (".py", ".html"))
    for bug in doc["bugs"]:
        assert f"PLANTED {bug['id']}" in source or bug["id"] == "CR-12", bug["id"]


def test_clinic(demo):
    m = demo("clinic")
    c = m.app.test_client()
    login(c, "reception@carepoint.test", "Front#2026")
    assert c.get("/prescriptions").status_code == 403  # correct
    assert c.get("/reports").status_code == 200  # CL-03
    slot = {"patient_id": "1", "doctor_id": "1", "date": d(4), "time": "10:00", "reason": "x"}
    assert c.post("/appointments/new", data=slot).status_code == 302
    assert (
        c.post("/appointments/new", data=dict(slot, patient_id="2")).status_code == 302
    )  # CL-01 double booking
    past = c.post("/appointments/new", data=dict(slot, date=d(-1)))
    assert b"cannot be booked in the past" in past.data  # correct
    # CL-09 + CL-02: complete the cancelled appointment #4 (Aisha Khan, 50% coverage, dermatology $120)
    c.post("/appointments/4/complete")
    inv = [i for i in m.store.all("invoices") if i["appointment_id"] == 4][0]
    assert inv["total"] == 120.0 and inv["coverage_pct"] == 50
    # CL-07: visits counter unchanged
    assert m.store.get("patients", 3)["visits"] == 0
    login(c, "dr.lee@carepoint.test", "Doctor#2026")
    assert c.get("/doctors/new").status_code == 200  # CL-04
    assert c.get("/appointments/8").status_code == 403  # correct: another doctor's appointment


def test_car_rental(demo):
    m = demo("car_rental")
    c = m.app.test_client()
    assert m.rental_quote(50, d(1), d(1))["total"] == 0  # CR-03
    assert m.rental_quote(50, d(1), d(8))["discount"] == 0  # CR-08 (7 days)
    assert m.rental_quote(50, d(1), d(9))["discount"] == 40.0  # 8 days gets it
    login(c, "liam@drivenow.test", "Drive#2026")
    assert c.get("/bookings/2").status_code == 200  # CR-04: Mei's booking
    assert c.get("/admin/revenue").status_code == 200  # CR-05
    assert (
        c.post("/bookings/new", data={"car_id": "1", "pickup_date": d(5), "return_date": d(2)}).status_code
        == 302
    )  # CR-01
    assert (
        c.post("/bookings/new", data={"car_id": "6", "pickup_date": d(20), "return_date": d(22)}).status_code
        == 302
    )  # CR-06
    login(c, "agent@drivenow.test", "Agent#2026")
    c.post("/bookings/3/return")
    assert m.store.get("bookings", 3)["status"] == "returned"
    assert m.store.get("cars", 3)["status"] == "rented"  # CR-15
    c.post("/bookings/3/pickup")
    assert m.store.get("bookings", 3)["status"] == "picked_up"  # CR-07
    assert (
        c.post("/bookings/4/cancel").status_code == 302
        and m.store.get("bookings", 4)["status"] == "cancelled"
    )


def test_shop_admin(demo):
    m = demo("shop_admin")
    c = m.app.test_client()
    login(c, "cashier@stockroom.test", "Till#2026")
    assert c.get("/purchases").status_code == 403  # correct
    assert c.get("/reports/profit").status_code == 200  # SH-03
    assert c.get("/products/1/edit").status_code == 200  # SH-09
    r = c.post("/sales/new", data={"product_3": "3", "qty_3": "10"})  # crisps: 3 in stock
    assert r.status_code == 302 and m.store.get("products", 3)["stock"] == -7  # SH-01
    sale = m.store.all("sales")[-1]
    assert sale["subtotal"] == 15.0 and sale["vat"] == 0.23  # SH-04 (should be 2.25)
    login(c, "admin@stockroom.test", "Admin#2026")
    c.post(
        "/purchases",
        data={"product_id": "5", "supplier": "Metro Distributors", "qty": "10", "unit_cost": "0.8"},
    )
    assert m.store.get("products", 5)["stock"] == 15  # SH-05
    before = m.store.get("products", 10)["stock"]
    c.post("/sales/5/refund")  # already refunded in the seed
    assert m.store.get("products", 10)["stock"] == before + 1  # SH-14
    assert (
        b"Gross profit" in c.get("/reports/profit").data and b"$0.00" in c.get("/reports/profit").data
    )  # SH-06

"""CarePoint Clinic — demo clinic management app (port 8101).

Roles: admin, doctor, receptionist. Contains planted bugs (see demo_targets/manifests/clinic_planted_bugs.json),
marked below with `# PLANTED CL-xx`.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

from flask import abort, flash, g, redirect, render_template, request, url_for

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from demo_kit import create_app, money, require_roles, run  # noqa: E402

APP_DIR = Path(__file__).resolve().parent
NAV = [
    ("Dashboard", "dashboard", ("admin", "doctor", "receptionist")),
    ("Patients", "patients", ("admin", "doctor", "receptionist")),
    ("Appointments", "appointments", ("admin", "doctor", "receptionist")),
    ("Prescriptions", "prescriptions", ("admin", "doctor")),
    ("Doctors", "doctors", ("admin", "receptionist")),
    ("Billing", "billing", ("admin", "receptionist")),
    ("Reports", "reports", ("admin",)),
]
app, store = create_app("clinic", APP_DIR, brand="CarePoint Clinic", tagline="Clinic management",
                        accent="#0f766e", nav=NAV)
app.jinja_env.filters["money"] = money
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
TRANSITIONS = {"check_in": ("scheduled", "checked_in"), "cancel": ("scheduled", "cancelled")}


def lookup(collection: str, item_id: int) -> dict:
    row = store.get(collection, item_id)
    if row is None:
        abort(404)
    return row


def names(collection: str) -> dict[int, str]:
    return {r["id"]: r["name"] for r in store.all(collection)}


# ---------------------------------------------------------------- dashboard


@app.route("/")
@require_roles()
def dashboard():
    appts = store.all("appointments")
    if g.user["role"] == "doctor":
        appts = [a for a in appts if a["doctor_id"] == g.user["doctor_id"]]
    upcoming = sorted([a for a in appts if a["status"] in ("scheduled", "checked_in")], key=lambda a: (a["date"], a["time"]))
    stats = {
        "patients": len(store.all("patients")),
        "upcoming": len(upcoming),
        "unpaid": sum(1 for i in store.all("invoices") if i["status"] == "unpaid"),
        "doctors": sum(1 for d in store.all("doctors") if d["active"]),
    }
    return render_template("dashboard.html", stats=stats, upcoming=upcoming[:8], patients=names("patients"),
                           doctors=names("doctors"))


# ---------------------------------------------------------------- patients


@app.route("/patients")
@require_roles("admin", "doctor", "receptionist")
def patients():
    q = request.args.get("q", "").strip().lower()
    rows = store.all("patients")
    if q:
        rows = [p for p in rows if q in p["name"].lower() or q in p["phone"] or q in p["email"].lower()]
    return render_template("patients.html", rows=rows, q=q)


def _validate_patient(form) -> tuple[dict, list[str]]:
    data = {
        "name": form.get("name", "").strip(),
        "dob": form.get("dob", "").strip(),
        "phone": form.get("phone", "").strip(),
        "email": form.get("email", "").strip(),
        "insurance_provider": form.get("insurance_provider", "").strip(),
        "coverage_pct": form.get("coverage_pct", "0").strip() or "0",
    }
    errors = []
    if len(data["name"]) < 2:
        errors.append("Name is required.")
    if not data["dob"]:
        errors.append("Date of birth is required.")
    # PLANTED CL-06: a date of birth in the future is accepted (no check against today).
    # PLANTED CL-05: the phone number is never validated — letters and symbols are saved as-is.
    if data["email"] and not EMAIL.match(data["email"]):
        errors.append("Email address is not valid.")
    try:
        cov = int(data["coverage_pct"])
        if not 0 <= cov <= 100:
            errors.append("Insurance coverage must be between 0 and 100%.")
        data["coverage_pct"] = cov
    except ValueError:
        errors.append("Insurance coverage must be a whole number.")
    return data, errors


@app.route("/patients/new", methods=["GET", "POST"])
@require_roles("admin", "receptionist")
def patient_new():
    data, errors = {}, []
    if request.method == "POST":
        data, errors = _validate_patient(request.form)
        if not errors:
            patient = store.insert("patients", dict(data, visits=0))
            flash(f"Patient {patient['name']} registered.", "success")
            return redirect(url_for("patient_detail", pid=patient["id"]))
    return render_template("patient_form.html", data=data, errors=errors)


@app.route("/patients/<int:pid>")
@require_roles("admin", "doctor", "receptionist")
def patient_detail(pid: int):
    patient = lookup("patients", pid)
    appts = [a for a in store.all("appointments") if a["patient_id"] == pid]
    rx = [r for r in store.all("prescriptions") if r["patient_id"] == pid]
    invoices = [i for i in store.all("invoices") if i["patient_id"] == pid]
    # PLANTED CL-07: "Completed visits" shows the stored counter, which is never updated when an appointment
    # is completed, instead of counting completed appointments.
    return render_template("patient_detail.html", p=patient, appts=appts, rx=rx, invoices=invoices,
                           doctors=names("doctors"), visits=patient.get("visits", 0))


@app.route("/patients/<int:pid>/delete", methods=["POST"])
@require_roles("admin")
def patient_delete(pid: int):
    lookup("patients", pid)
    store.delete("patients", pid)
    flash("Patient deleted.", "success")
    return redirect(url_for("patients"))


# ---------------------------------------------------------------- doctors


@app.route("/doctors")
@require_roles("admin", "receptionist")
def doctors():
    return render_template("doctors.html", rows=store.all("doctors"))


@app.route("/doctors/new", methods=["GET", "POST"])
@require_roles()  # PLANTED CL-04: any logged-in role can add a doctor via the direct URL (only the link is hidden)
def doctor_new():
    errors, data = [], {}
    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in ("name", "specialty", "fee")}
        if len(data["name"]) < 2:
            errors.append("Name is required.")
        if not data["specialty"]:
            errors.append("Specialty is required.")
        try:
            fee = float(data["fee"])
            if fee <= 0:
                errors.append("Consultation fee must be greater than 0.")
        except ValueError:
            errors.append("Consultation fee must be a number.")
        if not errors:
            store.insert("doctors", {"name": data["name"], "specialty": data["specialty"], "fee": fee, "active": True})
            flash("Doctor added.", "success")
            return redirect(url_for("doctors"))
    return render_template("doctor_form.html", errors=errors, data=data)


@app.route("/doctors/<int:did>/deactivate", methods=["POST"])
@require_roles("admin")
def doctor_deactivate(did: int):
    lookup("doctors", did)
    store.update("doctors", did, active=False)
    flash("Doctor deactivated. They can no longer be booked.", "success")
    return redirect(url_for("doctors"))


# ---------------------------------------------------------------- appointments


@app.route("/appointments")
@require_roles("admin", "doctor", "receptionist")
def appointments():
    rows = store.all("appointments")
    if g.user["role"] == "doctor":
        rows = [a for a in rows if a["doctor_id"] == g.user["doctor_id"]]
    status = request.args.get("status", "")
    if status:
        rows = [a for a in rows if a["status"] == status]
    rows.sort(key=lambda a: (a["date"], a["time"]))
    return render_template("appointments.html", rows=rows, patients=names("patients"), doctors=names("doctors"),
                           status=status)


@app.route("/appointments/new", methods=["GET", "POST"])
@require_roles("admin", "receptionist")
def appointment_new():
    errors, data = [], {}
    # PLANTED CL-08: deactivated doctors are still offered in the booking dropdown.
    doctor_options = store.all("doctors")
    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in ("patient_id", "doctor_id", "date", "time", "reason")}
        if not data["patient_id"] or not data["doctor_id"]:
            errors.append("Patient and doctor are required.")
        if not data["date"] or not data["time"]:
            errors.append("Date and time are required.")
        elif data["date"] < date.today().isoformat():
            errors.append("Appointments cannot be booked in the past.")
        # PLANTED CL-01: no check that the doctor is free — the same doctor can be double-booked at the same time.
        if not errors:
            appt = store.insert("appointments", {
                "patient_id": int(data["patient_id"]), "doctor_id": int(data["doctor_id"]), "date": data["date"],
                "time": data["time"], "reason": data["reason"], "status": "scheduled",
            })
            flash("Appointment booked.", "success")
            return redirect(url_for("appointment_detail", aid=appt["id"]))
    return render_template("appointment_form.html", errors=errors, data=data, patients=store.all("patients"),
                           doctors=doctor_options)


@app.route("/appointments/<int:aid>")
@require_roles("admin", "doctor", "receptionist")
def appointment_detail(aid: int):
    appt = lookup("appointments", aid)
    if g.user["role"] == "doctor" and appt["doctor_id"] != g.user["doctor_id"]:
        abort(403)
    rx = [r for r in store.all("prescriptions") if r["appointment_id"] == aid]
    invoice = next((i for i in store.all("invoices") if i["appointment_id"] == aid), None)
    return render_template("appointment_detail.html", a=appt, patient=store.get("patients", appt["patient_id"]),
                           doctor=store.get("doctors", appt["doctor_id"]), rx=rx, invoice=invoice)


@app.route("/appointments/<int:aid>/<action>", methods=["POST"])
@require_roles("admin", "doctor", "receptionist")
def appointment_action(aid: int, action: str):
    appt = lookup("appointments", aid)
    if action in TRANSITIONS:
        before, after = TRANSITIONS[action]
        if appt["status"] != before:
            flash(f"Cannot {action.replace('_', ' ')} an appointment that is {appt['status'].replace('_', ' ')}.", "error")
        else:
            store.update("appointments", aid, status=after)
            flash(f"Appointment {after.replace('_', ' ')}.", "success")
    elif action == "complete":
        # PLANTED CL-09: "complete" is only blocked for already-completed appointments, so a *cancelled*
        # appointment can be completed (and invoiced).
        if appt["status"] == "completed":
            flash("Appointment is already completed.", "error")
        else:
            store.update("appointments", aid, status="completed")
            doctor = store.get("doctors", appt["doctor_id"]) or {"fee": 0}
            patient = store.get("patients", appt["patient_id"]) or {"coverage_pct": 0}
            coverage = patient.get("coverage_pct", 0)
            # PLANTED CL-02: the invoice total ignores insurance coverage (should be fee × (1 − coverage%)).
            store.insert("invoices", {
                "appointment_id": aid, "patient_id": appt["patient_id"], "amount": doctor["fee"],
                "coverage_pct": coverage, "total": doctor["fee"], "status": "unpaid", "date": date.today().isoformat(),
            })
            flash("Appointment completed and invoice created.", "success")
    else:
        abort(404)
    return redirect(url_for("appointment_detail", aid=aid))


# ---------------------------------------------------------------- prescriptions


@app.route("/prescriptions")
@require_roles("admin", "doctor")
def prescriptions():
    rows = store.all("prescriptions")
    if g.user["role"] == "doctor":
        rows = [r for r in rows if r["doctor_id"] == g.user["doctor_id"]]
    return render_template("prescriptions.html", rows=rows, patients=names("patients"), doctors=names("doctors"))


@app.route("/appointments/<int:aid>/prescribe", methods=["GET", "POST"])
@require_roles("doctor")
def prescribe(aid: int):
    appt = lookup("appointments", aid)
    if appt["doctor_id"] != g.user["doctor_id"]:
        abort(403)
    errors, data = [], {}
    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in ("medication", "dosage", "days")}
        if not data["medication"]:
            errors.append("Medication is required.")
        if not data["dosage"]:
            errors.append("Dosage is required.")
        try:
            days = int(data["days"])  # PLANTED CL-15: zero or negative duration is accepted.
        except ValueError:
            errors.append("Duration must be a whole number of days.")
        if not errors:
            store.insert("prescriptions", {
                "appointment_id": aid, "patient_id": appt["patient_id"], "doctor_id": appt["doctor_id"],
                "medication": data["medication"], "dosage": data["dosage"], "days": days,
                "date": date.today().isoformat(),
            })
            flash("Prescription saved.", "success")
            return redirect(url_for("appointment_detail", aid=aid))
    return render_template("prescription_form.html", a=appt, errors=errors, data=data,
                           patient=store.get("patients", appt["patient_id"]))


# ---------------------------------------------------------------- billing & reports


@app.route("/billing")
@require_roles("admin", "receptionist")
def billing():
    return render_template("billing.html", rows=store.all("invoices"), patients=names("patients"))


@app.route("/billing/<int:iid>/pay", methods=["POST"])
@require_roles("admin", "receptionist")
def invoice_pay(iid: int):
    inv = lookup("invoices", iid)
    if inv["status"] == "paid":
        flash("Invoice is already paid.", "error")
    else:
        store.update("invoices", iid, status="paid")
        flash("Invoice marked as paid.", "success")
    return redirect(url_for("billing"))


@app.route("/reports")
@require_roles()  # PLANTED CL-03: reports are admin-only in the menu, but any logged-in role can open the URL.
def reports():
    invoices = store.all("invoices")
    # PLANTED CL-14: "Revenue collected" is labelled as paid invoices but also sums unpaid ones.
    collected = sum(i["total"] for i in invoices)
    outstanding = sum(i["total"] for i in invoices if i["status"] == "unpaid")
    per_doctor: dict[str, int] = {}
    doctors = names("doctors")
    for a in store.all("appointments"):
        if a["status"] == "completed":
            per_doctor[doctors.get(a["doctor_id"], "?")] = per_doctor.get(doctors.get(a["doctor_id"], "?"), 0) + 1
    return render_template("reports.html", collected=collected, outstanding=outstanding, per_doctor=per_doctor,
                           invoices=len(invoices))


@app.route("/help")
@require_roles()
def help_page():
    return render_template("help.html")


if __name__ == "__main__":
    run(app, store, 8101)

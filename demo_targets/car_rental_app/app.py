"""DriveNow Rentals — demo car rental app (port 8102).

Roles: admin, agent, customer. Contains planted bugs (see demo_targets/manifests/car_rental_planted_bugs.json),
marked below with `# PLANTED CR-xx`.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

from flask import abort, flash, g, redirect, render_template, request, url_for

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from demo_kit import create_app, money, require_roles, run  # noqa: E402

APP_DIR = Path(__file__).resolve().parent
NAV = [
    ("Dashboard", "dashboard", ("admin", "agent", "customer")),
    ("Fleet", "cars", ("admin", "agent", "customer")),
    ("Availability", "calendar", ("admin", "agent", "customer")),
    ("Bookings", "bookings", ("admin", "agent", "customer")),
    ("Invoices", "invoices", ("admin", "agent", "customer")),
    ("Revenue", "revenue", ("admin",)),
]
app, store = create_app("car_rental", APP_DIR, brand="DriveNow Rentals", tagline="Car rental operations",
                        accent="#c2410c", nav=NAV)
app.jinja_env.filters["money"] = money
WEEKLY_DISCOUNT = 0.10


def lookup(collection: str, item_id: int) -> dict:
    row = store.get(collection, item_id)
    if row is None:
        abort(404)
    return row


def car_names() -> dict[int, str]:
    return {c["id"]: f"{c['make']} {c['model']}" for c in store.all("cars")}


def user_names() -> dict[int, str]:
    return {u["id"]: u["name"] for u in store.all("users")}


def rental_quote(daily_rate: float, pickup: str, ret: str) -> dict:
    """Rental days = return − pickup, minimum 1. Rentals of 7 days or more get 10% off."""
    days = (date.fromisoformat(ret) - date.fromisoformat(pickup)).days  # PLANTED CR-03: no "minimum 1 day"
    subtotal = round(days * daily_rate, 2)
    # PLANTED CR-08: the weekly discount starts at 8 days instead of 7 (boundary off by one).
    discount = round(subtotal * WEEKLY_DISCOUNT, 2) if days > 7 else 0.0
    return {"days": days, "subtotal": subtotal, "discount": discount, "total": round(subtotal - discount, 2)}


# ---------------------------------------------------------------- dashboard


@app.route("/")
@require_roles()
def dashboard():
    bookings = store.all("bookings")
    if g.user["role"] == "customer":
        bookings = [b for b in bookings if b["customer_id"] == g.user["id"]]
    cars = store.all("cars")
    stats = {
        "available": sum(1 for c in cars if c["status"] == "available"),
        "rented": sum(1 for c in cars if c["status"] == "rented"),
        "maintenance": sum(1 for c in cars if c["status"] == "maintenance"),
        "active": sum(1 for b in bookings if b["status"] in ("reserved", "picked_up")),
    }
    upcoming = sorted([b for b in bookings if b["status"] == "reserved"], key=lambda b: b["pickup_date"])[:6]
    return render_template("dashboard.html", stats=stats, upcoming=upcoming, cars=car_names(), users=user_names())


# ---------------------------------------------------------------- fleet


@app.route("/cars")
@require_roles()
def cars():
    category = request.args.get("category", "")
    rows = store.all("cars")
    if category:
        rows = [c for c in rows if c["category"] == category]
    return render_template("cars.html", rows=rows, category=category)


@app.route("/cars/<int:cid>")
@require_roles()
def car_detail(cid: int):
    car = lookup("cars", cid)
    history = [b for b in store.all("bookings") if b["car_id"] == cid]
    return render_template("car_detail.html", c=car, history=history, users=user_names())


@app.route("/cars/new", methods=["GET", "POST"])
@require_roles("admin")
def car_new():
    errors, data = [], {}
    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in ("make", "model", "plate", "category", "daily_rate", "seats")}
        for field in ("make", "model", "plate"):
            if not data[field]:
                errors.append(f"{field.capitalize()} is required.")
        if any(c["plate"].lower() == data["plate"].lower() for c in store.all("cars")):
            errors.append("A car with this plate already exists.")
        try:
            rate = float(data["daily_rate"])  # PLANTED CR-09: zero or negative daily rates are accepted.
        except ValueError:
            errors.append("Daily rate must be a number.")
        try:
            seats = int(data["seats"] or 5)
            if not 2 <= seats <= 9:
                errors.append("Seats must be between 2 and 9.")
        except ValueError:
            errors.append("Seats must be a whole number.")
        if not errors:
            car = store.insert("cars", {"make": data["make"], "model": data["model"], "plate": data["plate"].upper(),
                                        "category": data["category"] or "Economy", "daily_rate": rate, "seats": seats,
                                        "status": "available", "image": "car-generic.svg"})
            flash("Car added to the fleet.", "success")
            return redirect(url_for("car_detail", cid=car["id"]))
    return render_template("car_form.html", errors=errors, data=data)


@app.route("/cars/<int:cid>/maintenance", methods=["POST"])
@require_roles("admin")
def car_maintenance(cid: int):
    car = lookup("cars", cid)
    if car["status"] == "rented":
        flash("A rented car cannot go to maintenance.", "error")
    else:
        store.update("cars", cid, status="available" if car["status"] == "maintenance" else "maintenance")
        flash("Car status updated.", "success")
    return redirect(url_for("car_detail", cid=cid))


@app.route("/calendar")
@require_roles()
def calendar():
    start = date.today()
    days = [start + timedelta(days=i) for i in range(14)]
    grid = {}
    for car in store.all("cars"):
        row = []
        for d in days:
            busy = any(b["car_id"] == car["id"] and b["status"] in ("reserved", "picked_up")
                       and b["pickup_date"] <= d.isoformat() < max(b["return_date"], b["pickup_date"])
                       for b in store.all("bookings"))
            row.append("maintenance" if car["status"] == "maintenance" else ("busy" if busy else "free"))
        grid[car["id"]] = row
    return render_template("calendar.html", days=days, grid=grid, cars=store.all("cars"))


# ---------------------------------------------------------------- bookings


@app.route("/bookings")
@require_roles()
def bookings():
    rows = store.all("bookings")
    if g.user["role"] == "customer":
        rows = [b for b in rows if b["customer_id"] == g.user["id"]]
    rows.sort(key=lambda b: b["pickup_date"], reverse=True)
    return render_template("bookings.html", rows=rows, cars=car_names(), users=user_names())


@app.route("/bookings/new", methods=["GET", "POST"])
@require_roles("agent", "customer")
def booking_new():
    errors, data, quote = [], {}, None
    # PLANTED CR-06: cars in maintenance are still offered for booking.
    car_options = [c for c in store.all("cars") if c["status"] != "retired"]
    customers = [u for u in store.all("users") if u["role"] == "customer"]
    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in ("car_id", "customer_id", "pickup_date", "return_date")}
        if g.user["role"] == "customer":
            data["customer_id"] = str(g.user["id"])
        if not data["car_id"] or not data["customer_id"]:
            errors.append("Car and customer are required.")
        if not data["pickup_date"] or not data["return_date"]:
            errors.append("Pickup and return dates are required.")
        elif data["pickup_date"] < date.today().isoformat():
            errors.append("Pickup date cannot be in the past.")
        # PLANTED CR-01: a return date before the pickup date is not rejected.
        # PLANTED CR-02: no overlap check — the same car can be booked twice for the same days.
        if not errors:
            car = lookup("cars", int(data["car_id"]))
            quote = rental_quote(car["daily_rate"], data["pickup_date"], data["return_date"])
            booking = store.insert("bookings", {
                "car_id": car["id"], "customer_id": int(data["customer_id"]), "pickup_date": data["pickup_date"],
                "return_date": data["return_date"], "status": "reserved", "daily_rate": car["daily_rate"],
                "quote_total": quote["total"],
            })
            flash(f"Booking confirmed. Estimated total {money(quote['total'])}.", "success")
            return redirect(url_for("booking_detail", bid=booking["id"]))
    return render_template("booking_form.html", errors=errors, data=data, cars=car_options, customers=customers)


@app.route("/bookings/<int:bid>")
@require_roles()
def booking_detail(bid: int):
    booking = lookup("bookings", bid)
    # PLANTED CR-04: customers are not restricted to their own bookings (any booking id can be opened).
    car = store.get("cars", booking["car_id"])
    quote = rental_quote(booking["daily_rate"], booking["pickup_date"], booking["return_date"])
    invoice = next((i for i in store.all("invoices") if i["booking_id"] == bid), None)
    return render_template("booking_detail.html", b=booking, car=car, quote=quote, invoice=invoice,
                           customer=store.get("users", booking["customer_id"]))


@app.route("/bookings/<int:bid>/<action>", methods=["POST"])
@require_roles("admin", "agent")
def booking_action(bid: int, action: str):
    booking = lookup("bookings", bid)
    status = booking["status"]
    if action == "pickup":
        # PLANTED CR-07: only "already picked up" is rejected, so a returned or cancelled booking can be picked up.
        if status == "picked_up":
            flash("This booking is already picked up.", "error")
        else:
            store.update("bookings", bid, status="picked_up")
            store.update("cars", booking["car_id"], status="rented")
            flash("Car handed over to the customer.", "success")
    elif action == "return":
        if status != "picked_up":
            flash("Only picked-up bookings can be returned.", "error")
        else:
            today = date.today().isoformat()
            actual_return = max(today, booking["pickup_date"])
            quote = rental_quote(booking["daily_rate"], booking["pickup_date"], actual_return)
            store.update("bookings", bid, status="returned", actual_return=actual_return)
            # PLANTED CR-15: the car's status is not set back to "available" after it is returned.
            store.insert("invoices", {"booking_id": bid, "customer_id": booking["customer_id"], "days": quote["days"],
                                      "subtotal": quote["subtotal"], "discount": quote["discount"],
                                      "total": quote["total"], "status": "unpaid", "date": today})
            flash("Car returned and invoice created.", "success")
    elif action == "cancel":
        if status != "reserved":
            flash("Only reserved bookings can be cancelled.", "error")
        else:
            store.update("bookings", bid, status="cancelled")
            flash("Booking cancelled.", "success")
    else:
        abort(404)
    return redirect(url_for("booking_detail", bid=bid))


# ---------------------------------------------------------------- invoices & revenue


@app.route("/invoices")
@require_roles()
def invoices():
    rows = store.all("invoices")
    if g.user["role"] == "customer":
        rows = [i for i in rows if i["customer_id"] == g.user["id"]]
    return render_template("invoices.html", rows=rows, users=user_names())


@app.route("/invoices/<int:iid>/pay", methods=["POST"])
@require_roles("admin", "agent")
def invoice_pay(iid: int):
    inv = lookup("invoices", iid)
    if inv["status"] == "paid":
        flash("Invoice already paid.", "error")
    else:
        store.update("invoices", iid, status="paid")
        flash("Payment recorded.", "success")
    return redirect(url_for("invoices"))


@app.route("/admin/revenue")
@require_roles()  # PLANTED CR-05: the revenue report is admin-only in the menu but open to every role by URL.
def revenue():
    invoices_ = store.all("invoices")
    paid = sum(i["total"] for i in invoices_ if i["status"] == "paid")
    unpaid = sum(i["total"] for i in invoices_ if i["status"] == "unpaid")
    by_car: dict[str, float] = {}
    names = car_names()
    bookings_ = {b["id"]: b for b in store.all("bookings")}
    for inv in invoices_:
        if inv["status"] == "paid":
            car = names.get(bookings_.get(inv["booking_id"], {}).get("car_id"), "?")
            by_car[car] = round(by_car.get(car, 0) + inv["total"], 2)
    return render_template("revenue.html", paid=paid, unpaid=unpaid, by_car=by_car)


@app.route("/rental-terms")
@require_roles()
def terms_page():
    return render_template("terms.html", discount=int(WEEKLY_DISCOUNT * 100))


if __name__ == "__main__":
    run(app, store, 8102)

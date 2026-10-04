"""StockRoom POS — demo shop admin app (port 8103).

Roles: admin, cashier. Contains planted bugs (see demo_targets/manifests/shop_admin_planted_bugs.json),
marked below with `# PLANTED SH-xx`.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from flask import abort, flash, g, redirect, render_template, request, url_for

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from demo_kit import create_app, money, require_roles, run  # noqa: E402

APP_DIR = Path(__file__).resolve().parent
NAV = [
    ("Dashboard", "dashboard", ("admin", "cashier")),
    ("New sale", "sale_new", ("admin", "cashier")),
    ("Sales", "sales", ("admin", "cashier")),
    ("Products", "products", ("admin", "cashier")),
    ("Purchases", "purchases", ("admin",)),
    ("Profit report", "profit_report", ("admin",)),
]
app, store = create_app("shop_admin", APP_DIR, brand="StockRoom POS", tagline="Shop back office",
                        accent="#7c3aed", nav=NAV)
app.jinja_env.filters["money"] = money
VAT_RATE = 15  # percent
LOW_STOCK = 5
SALE_LINES = 4


def lookup(collection: str, item_id: int) -> dict:
    row = store.get(collection, item_id)
    if row is None:
        abort(404)
    return row


def product_names() -> dict[int, str]:
    return {p["id"]: p["name"] for p in store.all("products")}


def sale_totals(subtotal: float) -> dict:
    """Prices exclude VAT; VAT is 15% of the subtotal."""
    vat = round(subtotal * VAT_RATE / 1000, 2)  # PLANTED SH-04: divides by 1000 — VAT is 1.5% instead of 15%.
    return {"subtotal": round(subtotal, 2), "vat": vat, "total": round(subtotal + vat, 2)}


# ---------------------------------------------------------------- dashboard


@app.route("/")
@require_roles()
def dashboard():
    today = date.today().isoformat()
    sales_today = [s for s in store.all("sales") if s["date"] == today and s["status"] == "completed"]
    products = [p for p in store.all("products") if p["active"]]
    # PLANTED SH-15: "Low stock" should list products below the threshold (stock < 5) but only lists stock == 0.
    low = [p for p in products if p["stock"] == 0]
    return render_template("dashboard.html", sales_today=sales_today, revenue_today=sum(s["total"] for s in sales_today),
                           low=low, product_count=len(products), threshold=LOW_STOCK)


# ---------------------------------------------------------------- products


@app.route("/products")
@require_roles()
def products():
    q = request.args.get("q", "").strip().lower()
    rows = store.all("products")
    if q:
        rows = [p for p in rows if q in p["name"].lower() or q in p["sku"].lower()]
    return render_template("products.html", rows=rows, q=q, threshold=LOW_STOCK)


def _product_form(existing: dict | None = None) -> tuple[dict, list[str]]:
    f = request.form
    data = {k: f.get(k, "").strip() for k in ("sku", "name", "category", "price", "cost", "stock")}
    errors = []
    if not data["sku"]:
        errors.append("SKU is required.")
    # PLANTED SH-08: SKU uniqueness is not checked — two products can share a SKU.
    if len(data["name"]) < 2:
        errors.append("Product name is required.")
    try:
        data["price"] = float(data["price"])  # PLANTED SH-07: zero or negative selling price is accepted.
    except ValueError:
        errors.append("Price must be a number.")
    try:
        data["cost"] = float(data["cost"])
        if data["cost"] < 0:
            errors.append("Cost cannot be negative.")
    except ValueError:
        errors.append("Cost must be a number.")
    try:
        data["stock"] = int(data["stock"] or (existing or {}).get("stock", 0))
        if data["stock"] < 0:
            errors.append("Opening stock cannot be negative.")
    except ValueError:
        errors.append("Stock must be a whole number.")
    return data, errors


@app.route("/products/new", methods=["GET", "POST"])
@require_roles("admin")
def product_new():
    data, errors = {}, []
    if request.method == "POST":
        data, errors = _product_form()
        if not errors:
            store.insert("products", dict(data, active=True))
            flash("Product created.", "success")
            return redirect(url_for("products"))
    return render_template("product_form.html", data=data, errors=errors, title="New product")


@app.route("/products/<int:pid>/edit", methods=["GET", "POST"])
@require_roles()  # PLANTED SH-09: cashiers can edit products (including prices) via the direct URL.
def product_edit(pid: int):
    product = lookup("products", pid)
    data, errors = product, []
    if request.method == "POST":
        data, errors = _product_form(product)
        if not errors:
            store.update("products", pid, **data)
            flash("Product updated.", "success")
            return redirect(url_for("products"))
    return render_template("product_form.html", data=data, errors=errors, title=f"Edit {product['name']}")


@app.route("/products/<int:pid>/deactivate", methods=["POST"])
@require_roles("admin")
def product_deactivate(pid: int):
    lookup("products", pid)
    store.update("products", pid, active=False)
    flash("Product removed from sale.", "success")
    return redirect(url_for("products"))


# ---------------------------------------------------------------- sales


@app.route("/sales")
@require_roles()
def sales():
    rows = sorted(store.all("sales"), key=lambda s: s["id"], reverse=True)
    users = {u["id"]: u["name"] for u in store.all("users")}
    return render_template("sales.html", rows=rows, users=users)


@app.route("/sales/new", methods=["GET", "POST"])
@require_roles()
def sale_new():
    # PLANTED SH-02: products removed from sale (inactive) are still offered here.
    options = store.all("products")
    errors, lines = [], []
    if request.method == "POST":
        for i in range(1, SALE_LINES + 1):
            pid, qty = request.form.get(f"product_{i}", ""), request.form.get(f"qty_{i}", "").strip()
            if not pid:
                continue
            try:
                q = int(qty or 1)
            except ValueError:
                errors.append(f"Line {i}: quantity must be a whole number.")
                continue
            if q < 1:
                errors.append(f"Line {i}: quantity must be at least 1.")
                continue
            product = lookup("products", int(pid))
            # PLANTED SH-01: quantity is not checked against stock, so stock can go negative.
            lines.append({"product_id": product["id"], "name": product["name"], "qty": q, "price": product["price"]})
        if not lines and not errors:
            errors.append("Add at least one product.")
        if not errors:
            totals = sale_totals(sum(line["qty"] * line["price"] for line in lines))
            for line in lines:
                product = store.get("products", line["product_id"])
                store.update("products", line["product_id"], stock=product["stock"] - line["qty"])
            sale = store.insert("sales", dict(totals, items=lines, status="completed", cashier_id=g.user["id"],
                                              date=date.today().isoformat(),
                                              payment=request.form.get("payment", "cash")))
            flash(f"Sale completed: {money(sale['total'])}.", "success")
            return redirect(url_for("sale_detail", sid=sale["id"]))
    return render_template("sale_form.html", options=options, errors=errors, lines=SALE_LINES, vat=VAT_RATE)


@app.route("/sales/<int:sid>")
@require_roles()
def sale_detail(sid: int):
    sale = lookup("sales", sid)
    cashier = store.get("users", sale["cashier_id"])
    return render_template("sale_detail.html", s=sale, cashier=cashier, vat=VAT_RATE)


@app.route("/sales/<int:sid>/refund", methods=["POST"])
@require_roles("admin")
def sale_refund(sid: int):
    sale = lookup("sales", sid)
    # PLANTED SH-14: a refunded sale can be refunded again; each refund puts the items back into stock.
    for line in sale["items"]:
        product = store.get("products", line["product_id"])
        if product:
            store.update("products", line["product_id"], stock=product["stock"] + line["qty"])
    store.update("sales", sid, status="refunded")
    flash("Sale refunded and items returned to stock.", "success")
    return redirect(url_for("sale_detail", sid=sid))


# ---------------------------------------------------------------- purchases & profit


@app.route("/purchases", methods=["GET", "POST"])
@require_roles("admin")
def purchases():
    errors = []
    if request.method == "POST":
        pid = request.form.get("product_id", "")
        supplier = request.form.get("supplier", "").strip()
        try:
            qty = int(request.form.get("qty", ""))
            unit_cost = float(request.form.get("unit_cost", ""))
            if qty < 1 or unit_cost < 0:
                errors.append("Quantity must be at least 1 and unit cost cannot be negative.")
        except ValueError:
            errors.append("Quantity and unit cost are required numbers.")
        if not pid or not supplier:
            errors.append("Product and supplier are required.")
        if not errors:
            lookup("products", int(pid))
            store.insert("purchases", {"product_id": int(pid), "supplier": supplier, "qty": qty, "unit_cost": unit_cost,
                                       "date": date.today().isoformat()})
            # PLANTED SH-05: receiving a purchase does not add the quantity to the product's stock.
            flash("Purchase recorded and stock received.", "success")
            return redirect(url_for("purchases"))
    rows = sorted(store.all("purchases"), key=lambda r: r["id"], reverse=True)
    return render_template("purchases.html", rows=rows, products=store.all("products"), names=product_names(),
                           errors=errors)


@app.route("/reports/profit")
@require_roles()  # PLANTED SH-03: the profit report is admin-only in the menu but cashiers can open it by URL.
def profit_report():
    products = {p["id"]: p for p in store.all("products")}
    revenue = cogs = 0.0
    rows: dict[str, dict] = {}
    for sale in store.all("sales"):
        if sale["status"] != "completed":
            continue
        for line in sale["items"]:
            product = products.get(line["product_id"], {})
            line_revenue = line["qty"] * line["price"]
            # PLANTED SH-06: cost of goods uses the product's *selling price* instead of its cost.
            line_cost = line["qty"] * product.get("price", 0)
            revenue += line_revenue
            cogs += line_cost
            r = rows.setdefault(line["name"], {"qty": 0, "revenue": 0.0, "cost": 0.0})
            r["qty"] += line["qty"]
            r["revenue"] += line_revenue
            r["cost"] += line_cost
    return render_template("profit.html", revenue=revenue, cogs=cogs, profit=revenue - cogs, rows=rows)


if __name__ == "__main__":
    run(app, store, 8103)

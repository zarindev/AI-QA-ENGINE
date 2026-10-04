"""Shared plumbing for the three QA Pilot demo apps (clinic, car rental, shop admin).

Each demo app is a small Flask app that keeps its data in one JSON file (no database, like QA Pilot itself):
    data/seed.json        committed seed data
    data/live_data.json   working copy (gitignored), recreated from the seed by POST /reset-demo-data

The apps contain *planted bugs* on purpose. They are listed in demo_targets/manifests/ (which the QA Pilot
engine never reads) and marked in the source with `# PLANTED <ID>` comments.
"""

from __future__ import annotations

import copy
import functools
import json
import os
import threading
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from jinja2 import ChoiceLoader, FileSystemLoader

COMMON_DIR = Path(__file__).resolve().parent


def _resolve_dates(value: Any, today: date) -> Any:
    """Seed files say {"$date": 3} for "three days from the reset day", so demo data never goes stale."""
    if isinstance(value, dict):
        if set(value) == {"$date"}:
            return (today + timedelta(days=int(value["$date"]))).isoformat()
        return {k: _resolve_dates(v, today) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_dates(v, today) for v in value]
    return value


class JsonStore:
    """Thread-safe JSON document store: one dict of collections, written atomically after each change."""

    def __init__(self, data_dir: Path) -> None:
        self.seed_file = data_dir / "seed.json"
        # QAP_DEMO_LIVE_DIR lets tests (and the benchmark) keep their working copy away from yours.
        live_root = os.environ.get("QAP_DEMO_LIVE_DIR", "")
        live_dir = Path(live_root) / data_dir.parent.name if live_root else data_dir
        live_dir.mkdir(parents=True, exist_ok=True)
        self.live_file = live_dir / "live_data.json"
        self._lock = threading.RLock()
        if not self.live_file.exists():
            self.reset()
        self._data: dict[str, Any] = json.loads(self.live_file.read_text(encoding="utf-8"))

    def reset(self) -> None:
        with self._lock:
            data = json.loads(self.seed_file.read_text(encoding="utf-8"))
            self._data = _resolve_dates(data, date.today())
            self._write()

    def _write(self) -> None:
        tmp = self.live_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        os.replace(tmp, self.live_file)

    def all(self, collection: str) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._data.get(collection, []))

    def get(self, collection: str, item_id: int) -> dict[str, Any] | None:
        return next((r for r in self.all(collection) if r["id"] == item_id), None)

    def insert(self, collection: str, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            rows = self._data.setdefault(collection, [])
            record = dict(record, id=max((r["id"] for r in rows), default=0) + 1)
            rows.append(record)
            self._write()
            return copy.deepcopy(record)

    def update(self, collection: str, item_id: int, **fields: Any) -> dict[str, Any] | None:
        with self._lock:
            for row in self._data.get(collection, []):
                if row["id"] == item_id:
                    row.update(fields)
                    self._write()
                    return copy.deepcopy(row)
        return None

    def delete(self, collection: str, item_id: int) -> None:
        with self._lock:
            self._data[collection] = [r for r in self._data.get(collection, []) if r["id"] != item_id]
            self._write()

    def meta(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return copy.deepcopy(self._data.get("_meta", {}).get(key, default))


def create_app(
    name: str,
    app_dir: Path,
    *,
    brand: str,
    tagline: str,
    accent: str,
    nav: list[tuple[str, str, tuple[str, ...]]],
) -> tuple[Flask, JsonStore]:
    """Build a Flask app with login, role-aware navigation, flash messages and the reset route.

    `nav` is a list of (label, endpoint, roles allowed to *see* the link). Showing a link is not the same as
    protecting the route — each view protects itself with `@require_roles`.
    """
    app = Flask(name, template_folder=str(app_dir / "templates"), static_folder=str(app_dir / "static"))
    app.jinja_loader = ChoiceLoader([FileSystemLoader(str(app_dir / "templates")),
                                     FileSystemLoader(str(COMMON_DIR / "templates"))])
    app.secret_key = f"qa-pilot-demo-{name}-not-a-real-secret"
    store = JsonStore(app_dir / "data")

    @app.before_request
    def load_user() -> None:
        uid = session.get("user_id")
        g.user = store.get("users", uid) if uid else None

    @app.context_processor
    def inject() -> dict[str, Any]:
        role = g.user["role"] if g.get("user") else None
        items = [(label, endpoint) for label, endpoint, roles in nav if role and role in roles]
        return {"brand": brand, "tagline": tagline, "accent": accent, "nav_items": items, "current_user": g.get("user")}

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = ""
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = next((u for u in store.all("users") if u["email"] == email and u["password"] == password), None)
            if user:
                session.clear()
                session["user_id"] = user["id"]
                return redirect(request.args.get("next") or url_for("dashboard"))
            error = "Invalid email or password."
        return render_template("login.html", error=error, demo_users=store.all("users"))

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/reset-demo-data", methods=["POST"])
    def reset_demo_data():
        store.reset()
        session.clear()
        flash("Demo data was reset.", "info")
        return redirect(url_for("login"))

    @app.route("/favicon.ico")
    def favicon():
        from flask import send_from_directory

        return send_from_directory(COMMON_DIR / "static", "favicon.svg", mimetype="image/svg+xml")

    @app.route("/assets/kit.css")
    def kit_css():
        from flask import send_from_directory

        return send_from_directory(COMMON_DIR / "static", "kit.css")

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403, message="You do not have permission to view this page."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, message="Page not found."), 404

    return app, store


def require_roles(*roles: str) -> Callable:
    """Login required, and (if roles are given) the user's role must be one of them."""

    def decorator(view: Callable) -> Callable:
        @functools.wraps(view)
        def wrapped(*args: Any, **kwargs: Any):
            if not g.get("user"):
                return redirect(url_for("login", next=request.path))
            if roles and g.user["role"] not in roles:
                from flask import abort

                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def money(value: float) -> str:
    return f"${value:,.2f}"


def run(app: Flask, store: JsonStore, port: int) -> None:
    """`python app.py` serves on localhost; `python app.py --reset` restores the seed data first."""
    import sys

    if "--reset" in sys.argv:
        store.reset()
        print("Demo data reset.")
    print(f"Serving on http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)

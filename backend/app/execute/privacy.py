"""Privacy blur for screenshots and videos (emails, phone numbers, people's names).

When a screenshot is taken we ask the page where personal data is drawn — text matching email / phone patterns,
cells in table columns about people (name, patient, customer, employee, doctor…), and the value next to labels
like "Patient" or "Email" — and store those boxes next to the image (`<image>.pii.json`). The original stays
intact for debugging; exports, bug evidence and videos use blurred copies when the project's privacy blur is on
(default: on for healthcare and banking).
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter

PII_RECTS_JS = r"""
const EMAIL = /[\w.+-]+@[\w-]+\.[\w.-]+/;
const PHONE = /(\+?\d[\d\s().-]{7,}\d)/;
const PERSON = /\b(name|patient|customer|client|employee|doctor|cashier|user|guest|tenant|student|owner|contact|agent|member)\b/i;
const rects = [];
const add = r => { if (r.width > 1 && r.height > 1 && r.bottom > 0 && r.top < innerHeight) rects.push({x: r.left, y: r.top, width: r.width, height: r.height}); };
// 1. text that looks like an email or a phone number
const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
let node;
while ((node = walker.nextNode())) {
  const t = node.textContent;
  if (!t || t.length > 400 || !(EMAIL.test(t) || PHONE.test(t))) continue;
  const parent = node.parentElement;
  if (!parent || parent.closest('script,style') || parent.offsetParent === null) continue;
  const range = document.createRange(); range.selectNodeContents(node);
  for (const r of range.getClientRects()) add(r);
}
// 2. table columns about people
for (const table of document.querySelectorAll('table')) {
  const headRow = table.querySelector('thead tr') || table.querySelector('tr');
  if (!headRow) continue;
  const heads = Array.from(headRow.children);
  heads.forEach((th, i) => {
    if (!PERSON.test(th.innerText || '')) return;
    for (const row of table.querySelectorAll('tr')) {
      if (row === headRow) continue;
      const cell = row.children[i];
      if (cell && cell.innerText.trim()) add(cell.getBoundingClientRect());
    }
  });
}
// 3. "Label: value" pairs (dl/dt/dd, and label + input values)
for (const dt of document.querySelectorAll('dt')) {
  if (PERSON.test(dt.innerText || '') || /email|phone/i.test(dt.innerText || '')) {
    const dd = dt.nextElementSibling; if (dd) add(dd.getBoundingClientRect());
  }
}
for (const input of document.querySelectorAll('input:not([type=hidden]):not([type=password])')) {
  const label = (input.labels && input.labels[0] ? input.labels[0].innerText : input.name) || '';
  if ((PERSON.test(label) || /email|phone/i.test(label)) && input.value) add(input.getBoundingClientRect());
}
// 4. the signed-in user's name, shown next to "Log out" / "Sign out"
for (const link of document.querySelectorAll('a, button')) {
  if (!/^\s*(log|sign)\s*out\s*$/i.test(link.innerText || '')) continue;
  const box = link.parentElement;
  if (!box) continue;
  for (const el of box.children) {
    if (el !== link && !el.contains(link) && (el.innerText || '').trim() && (el.innerText || '').length < 60) {
      if (!/^(admin|doctor|receptionist|agent|customer|cashier|manager|user|staff)$/i.test(el.innerText.trim())) add(el.getBoundingClientRect());
    }
  }
}
return {width: innerWidth, rects: rects.slice(0, 400)};
"""


def pii_rects(driver: Any) -> dict[str, Any] | None:
    """{"width": viewport CSS width, "rects": [...]} or None when nothing personal is on screen."""
    try:
        data = driver.execute_script(PII_RECTS_JS)
    except Exception:  # privacy detection must never break a test
        return None
    return data if isinstance(data, dict) and data.get("rects") else None


def sidecar(path: Path) -> Path:
    return path.with_name(path.name + ".pii.json")


def sidecar_text(data: dict[str, Any]) -> str:
    return json.dumps(data)


def load(path: Path) -> tuple[list[dict[str, float]], int | None]:
    """Rects and the viewport width they were measured at (older sidecars are a bare list)."""
    side = sidecar(path)
    if not side.exists():
        return [], None
    try:
        data = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], None
    if isinstance(data, list):
        return data, None
    return list(data.get("rects") or []), data.get("width")


def load_rects(path: Path) -> list[dict[str, float]]:
    return load(path)[0]


def blur(
    image: bytes, rects: list[dict[str, float]], viewport_width: int | None = None, fmt: str | None = None
) -> bytes:
    """Gaussian-blur every rect (CSS px of the viewport, scaled to the image). Returns bytes in the same format."""
    opened = Image.open(io.BytesIO(image))
    out_fmt = fmt or (opened.format or "PNG")
    img = opened.convert("RGB")
    scale = img.width / viewport_width if viewport_width else 1.0
    for r in rects:
        box = (
            max(0, int(r["x"] * scale) - 3),
            max(0, int(r["y"] * scale) - 3),
            min(img.width, int((r["x"] + r["width"]) * scale) + 3),
            min(img.height, int((r["y"] + r["height"]) * scale) + 3),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        region = img.crop(box).filter(ImageFilter.GaussianBlur(radius=max(6, (box[3] - box[1]) // 3)))
        img.paste(region, box)
    buf = io.BytesIO()
    img.save(buf, "JPEG" if out_fmt.upper() in ("JPEG", "JPG") else "PNG", quality=80)
    return buf.getvalue()


def blurred_bytes(path: Path, viewport_width: int | None = None) -> bytes:
    data = path.read_bytes()
    rects, measured = load(path)
    return blur(data, rects, measured or viewport_width or 1440) if rects else data


def privacy_enabled(project: Any, domain: str) -> bool:
    """Project setting wins; otherwise the domain pack decides (healthcare and banking blur by default)."""
    if getattr(project, "privacy_blur", None) is not None:
        return bool(project.privacy_blur)
    from app.understand.packs import get_pack

    pack = get_pack(domain)
    return bool(pack and pack.privacy_blur)

"""Simplified DOM snapshot: indexed interactive elements, forms, tables, headings and links.

The in-page script tags every interactive element with `data-qap-index="N"` so later actions can target
`[N]` directly, and computes a locator set for each element so recorded steps can be replayed later.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from app.storage.schemas import Element, Form, FormPurpose, LocatorSet, Table

SNAPSHOT_JS = r"""
const MAX_ELEMENTS = arguments[0] || 400;
const INTERACTIVE = 'a, button, input, select, textarea, summary, [contenteditable="true"], ' +
  '[role=button], [role=link], [role=menuitem], [role=tab], [role=checkbox], [role=radio], [role=switch], ' +
  '[role=combobox], [role=option], [onclick], [tabindex]:not([tabindex="-1"])';
const clean = s => (s || '').replace(/\s+/g, ' ').trim();

function visible(el) {
  if (el.type === 'hidden') return false;
  const r = el.getBoundingClientRect();
  const st = getComputedStyle(el);
  if (st.visibility === 'hidden' || st.display === 'none' || parseFloat(st.opacity) === 0) {
    // custom checkboxes/radios often hide the real input; keep it if its label is visible
    if (!(el.tagName === 'INPUT' && ['checkbox','radio','file'].includes(el.type) && el.labels && el.labels.length)) return false;
  }
  if (r.width === 0 && r.height === 0 && !(el.labels && el.labels.length)) return false;
  return true;
}

function labelFor(el) {
  const aria = el.getAttribute('aria-label');
  if (aria) return clean(aria);
  const by = el.getAttribute('aria-labelledby');
  if (by) {
    const t = by.split(/\s+/).map(id => document.getElementById(id)).filter(Boolean).map(n => n.innerText).join(' ');
    if (clean(t)) return clean(t);
  }
  if (el.labels && el.labels.length) return clean(Array.from(el.labels).map(l => l.innerText).join(' '));
  if (el.id) {
    const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
    if (l) return clean(l.innerText);
  }
  return '';
}

function ownText(el) {
  if (['INPUT','SELECT','TEXTAREA'].includes(el.tagName)) return '';
  let t = clean(el.innerText || el.textContent);
  if (!t) {
    const img = el.querySelector('img[alt]');
    if (img) t = clean(img.alt);
  }
  if (!t) t = clean(el.getAttribute('title'));
  return t.slice(0, 160);
}

function cssPath(el) {
  if (el.id && document.querySelectorAll('#' + CSS.escape(el.id)).length === 1) return '#' + CSS.escape(el.id);
  const parts = [];
  let node = el;
  while (node && node.nodeType === 1 && parts.length < 6) {
    let part = node.tagName.toLowerCase();
    if (node.id && document.querySelectorAll('#' + CSS.escape(node.id)).length === 1) { parts.unshift('#' + CSS.escape(node.id)); break; }
    const parent = node.parentElement;
    if (parent) {
      const same = Array.from(parent.children).filter(c => c.tagName === node.tagName);
      if (same.length > 1) part += ':nth-of-type(' + (same.indexOf(node) + 1) + ')';
    }
    parts.unshift(part);
    node = parent;
  }
  return parts.join(' > ');
}

function xPath(el) {
  const parts = [];
  let node = el;
  while (node && node.nodeType === 1) {
    let idx = 1, sib = node.previousElementSibling;
    while (sib) { if (sib.tagName === node.tagName) idx++; sib = sib.previousElementSibling; }
    parts.unshift(node.tagName.toLowerCase() + '[' + idx + ']');
    node = node.parentElement;
  }
  return '/' + parts.join('/');
}

document.querySelectorAll('[data-qap-index]').forEach(n => n.removeAttribute('data-qap-index'));
const forms = Array.from(document.forms);
const seen = new Set();
const elements = [];
for (const el of document.querySelectorAll(INTERACTIVE)) {
  if (elements.length >= MAX_ELEMENTS) break;
  if (seen.has(el) || !visible(el)) continue;
  // anchors without href are only interactive when the app made them clickable (SPA links)
  if (el.tagName === 'A' && !el.hasAttribute('href') && !el.getAttribute('role') && getComputedStyle(el).cursor !== 'pointer') continue;
  // skip containers whose interactive child is already listed (e.g. a div[onclick] wrapping a button)
  if (el.querySelector && el.matches('[onclick], [tabindex]') && !el.matches('a, button, input, select, textarea, [role]') &&
      el.querySelector('a[href], button, input, select, textarea')) continue;
  seen.add(el);
  const idx = elements.length;
  el.setAttribute('data-qap-index', String(idx));
  const r = el.getBoundingClientRect();
  const attrs = {};
  for (const a of ['id','name','type','role','aria-label','title','class','data-testid','data-test','data-qa','data-cy','formaction','autocomplete','inputmode']) {
    const v = el.getAttribute(a);
    if (v) attrs[a] = v.slice(0, 200);
  }
  const form = el.form || el.closest('form');
  const label = labelFor(el);
  const text = ownText(el);
  elements.push({
    index: idx,
    tag: el.tagName.toLowerCase(),
    type: (el.getAttribute('type') || '').toLowerCase(),
    role: el.getAttribute('role') || '',
    label: label,
    text: text,
    name: el.getAttribute('name') || '',
    placeholder: el.getAttribute('placeholder') || '',
    href: el.tagName === 'A' ? (el.getAttribute('href') || '') : '',
    value: ['INPUT','TEXTAREA'].includes(el.tagName) && !['password'].includes(el.type) ? String(el.value || '').slice(0, 100)
           : (el.tagName === 'SELECT' ? (el.options[el.selectedIndex] ? clean(el.options[el.selectedIndex].text) : '') : ''),
    required: !!(el.required || el.getAttribute('aria-required') === 'true'),
    disabled: !!(el.disabled || el.getAttribute('aria-disabled') === 'true'),
    pattern: el.getAttribute('pattern') || '',
    min: el.getAttribute('min') || '',
    max: el.getAttribute('max') || '',
    minlength: el.minLength > 0 ? el.minLength : null,
    maxlength: el.maxLength > 0 && el.maxLength < 524288 ? el.maxLength : null,
    options: el.tagName === 'SELECT' ? Array.from(el.options).slice(0, 50).map(o => clean(o.text)) : [],
    form_index: form ? forms.indexOf(form) : null,
    in_viewport: r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth,
    attributes: attrs,
    locators: {
      id: el.id || '',
      name: el.getAttribute('name') || '',
      test_id: el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-qa') || el.getAttribute('data-cy') || '',
      aria_label: el.getAttribute('aria-label') || '',
      text: text.slice(0, 80),
      label: label.slice(0, 80),
      placeholder: el.getAttribute('placeholder') || '',
      css: cssPath(el),
      xpath: xPath(el),
      tag: el.tagName.toLowerCase(),
    },
  });
}

const formInfo = forms.map((f, i) => {
  let heading = '';
  let n = f;
  for (let depth = 0; n && depth < 4 && !heading; depth++, n = n.parentElement) {
    const h = n.querySelector('h1, h2, h3, legend');
    if (h) heading = clean(h.innerText).slice(0, 120);
  }
  return {index: i, action: f.getAttribute('action') || '', method: (f.getAttribute('method') || 'get').toLowerCase(), heading,
          role: f.getAttribute('role') || '', id: f.id || '', name: f.getAttribute('name') || '', cls: f.className || ''};
});

const tables = Array.from(document.querySelectorAll('table, [role=table], [role=grid]')).slice(0, 20).map(t => {
  // Column headers only: the header row (thead, or the first row), not row headers like <th scope=row>.
  const headRow = t.querySelector('thead tr') || t.querySelector('tr, [role=row]');
  let headers = headRow ? Array.from(headRow.querySelectorAll('th, [role=columnheader]')).map(h => clean(h.innerText)).filter(Boolean) : [];
  if (!headers.length) headers = Array.from(t.querySelectorAll('[role=columnheader]')).map(h => clean(h.innerText)).filter(Boolean);
  const rows = t.querySelectorAll('tbody tr, [role=row]').length;
  const cap = t.querySelector('caption');
  return {headers: headers.slice(0, 40), row_count: rows, caption: cap ? clean(cap.innerText) : ''};
});

const headings = Array.from(document.querySelectorAll('h1, h2, h3')).filter(visible).map(h => clean(h.innerText)).filter(Boolean).slice(0, 30);
const links = Array.from(document.querySelectorAll('a[href]')).map(a => a.href).filter(Boolean);
const brokenImages = Array.from(document.images).filter(img => img.complete && img.naturalWidth === 0 && (img.currentSrc || img.src))
  .map(img => img.currentSrc || img.src).slice(0, 50);
const doc = document.documentElement;
return {
  url: location.href,
  title: document.title,
  headings,
  text: clean(document.body ? document.body.innerText : '').slice(0, 3000),
  elements,
  forms: formInfo,
  tables,
  links,
  broken_images: brokenImages,
  overflow_x: Math.max(doc.scrollWidth, document.body ? document.body.scrollWidth : 0) - doc.clientWidth,
  has_password: !!document.querySelector('input[type=password]'),
};
"""


class Snapshot:
    """Python view of SNAPSHOT_JS output."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.url: str = raw.get("url", "")
        self.title: str = raw.get("title", "")
        self.headings: list[str] = raw.get("headings", [])
        self.text: str = raw.get("text", "")
        self.elements = [_element(e) for e in raw.get("elements", [])]
        self.tables = [Table(**t) for t in raw.get("tables", [])]
        self.links: list[str] = sorted(set(raw.get("links", [])))
        self.broken_images: list[str] = raw.get("broken_images", [])
        self.overflow_x: int = int(raw.get("overflow_x") or 0)
        self.has_password: bool = bool(raw.get("has_password"))
        self.forms = self._forms(raw.get("forms", []))

    def _forms(self, raw_forms: list[dict[str, Any]]) -> list[Form]:
        forms = []
        for f in raw_forms:
            fields = [e for e in self.elements if e.form_index == f["index"]]
            submit = next(
                (
                    e.index
                    for e in fields
                    if (e.tag == "button" and e.type in ("", "submit"))
                    or (e.tag == "input" and e.type in ("submit", "image"))
                ),
                None,
            )
            form = Form(
                index=f["index"],
                action=f.get("action", ""),
                method=f.get("method", "get"),
                field_indices=[e.index for e in fields],
                submit_index=submit,
                heading=f.get("heading", ""),
            )
            form.purpose = classify_form(form, fields, f)
            forms.append(form)
        return forms

    def element(self, index: int) -> Element | None:
        return next((e for e in self.elements if e.index == index), None)

    def outline(self, max_elements: int = 250) -> str:
        """Compact text the AI reads each turn: title, headings, then one line per indexed element."""
        lines = [f"URL: {self.url}", f"Title: {self.title}"]
        if self.headings:
            lines.append("Headings: " + " | ".join(self.headings[:10]))
        for t in self.tables[:5]:
            lines.append(f"Table ({t.row_count} rows): " + ", ".join(t.headers[:15]))
        lines.append("Interactive elements:")
        lines.extend(e.describe() for e in self.elements[:max_elements])
        return "\n".join(lines)

    def absolute_links(self, base: str) -> list[str]:
        return sorted({urljoin(base, href) for href in self.links})


def _element(data: dict[str, Any]) -> Element:
    data = dict(data)
    data["locators"] = LocatorSet(**data.get("locators", {}))
    return Element(**data)


def classify_form(form: Form, fields: list[Element], raw: dict[str, Any]) -> FormPurpose:
    """Heuristic purpose; the AI refines it in stage ②."""
    types = {f.type for f in fields}
    blob = " ".join(
        [
            raw.get("role", ""),
            raw.get("id", ""),
            raw.get("name", ""),
            str(raw.get("cls", "")),
            form.action,
            form.heading,
        ]
        + [f.name + " " + f.label + " " + f.placeholder + " " + f.text for f in fields]
    ).lower()
    if (
        "password" in types
        and len([f for f in fields if f.tag == "input" and f.type not in ("hidden", "submit", "checkbox")])
        <= 3
    ):
        return "login"
    if raw.get("role") == "search" or "search" in types or "search" in blob:
        return "search"
    if "filter" in blob:
        return "filter"
    if any(w in blob for w in ("contact", "message", "enquiry", "inquiry")):
        return "contact"
    if any(w in blob for w in ("edit", "update")):
        return "edit"
    if any(w in blob for w in ("add", "new", "create", "register", "save")):
        return "create"
    return "other"


def take_snapshot(driver: Any, max_elements: int = 400) -> Snapshot:
    return Snapshot(driver.execute_script(SNAPSHOT_JS, max_elements))

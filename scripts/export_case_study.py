"""Build docs/case-study/case-study.html and export it with headless Chrome.

    python scripts/export_case_study.py

1. Fills docs/case-study/slides.html.j2 with real numbers from docs/benchmarks.json and screenshots from
   docs/assets/screenshots/ (embedded, so the HTML is one self-contained file).
2. Exports to docs/case-study/export/: the 12-page PDF, slides/slide-NN.png (1600×1200), upwork/ (thumbnail +
   6 gallery images, PNG and JPG < 2 MB) and social/ (GitHub 1280×640, LinkedIn/X 1200×675).
3. Checks every image's size and that no text overflows its slide.
"""

from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from jinja2 import Environment, FileSystemLoader  # noqa: E402
from PIL import Image  # noqa: E402

from app.browser.driver import BrowserSession  # noqa: E402

CS = ROOT / "docs" / "case-study"
SHOTS = ROOT / "docs" / "assets" / "screenshots"
EXPORT = CS / "export"
AUTHOR = "Md Zarin Tasnim"
ROLE = "QA Automation Engineer & AI Automation Developer"
GALLERY = [  # Upwork gallery, in upload order: (slide number, file name)
    (3, "01-solution"),
    (4, "02-any-industry"),
    (5, "03-knowledge-graph"),
    (7, "04-live-run"),
    (8, "05-bug-report"),
    (10, "06-results"),
]
DOMAINS = {  # what was detected / inferred on each demo app (see the runs' site_profile.json and requirements.json)
    "clinic": (
        "Healthcare · clinic management",
        "Insurance coverage on invoices, no double-booked doctors, inactive doctors not bookable, cancelled visits can’t be completed",
    ),
    "rental": (
        "Rental · car rental back office",
        "Minimum one-day rental, 10 % discount from 7 days, no overlapping bookings, cars in maintenance not bookable",
    ),
    "shop": (
        "E-commerce · retail point of sale",
        "Total = subtotal + VAT, stock moves on sale and refund, one refund per sale, profit report admin-only",
    ),
}


def data_uri(path: Path, width: int = 1500, quality: int = 84) -> str:
    img = Image.open(path).convert("RGB")
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def svg_uri(path: Path) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def context() -> dict:
    bench = json.loads((ROOT / "docs" / "benchmarks.json").read_text("utf-8"))
    apps = []
    for key in ("clinic", "rental", "shop"):
        a = bench["apps"].get(key)
        if not a:
            raise SystemExit(f"docs/benchmarks.json has no result for {key} — run scripts/benchmark.py first")
        apps.append(
            {
                "name": a["app"],
                "detected": DOMAINS[key][0],
                "inferred": DOMAINS[key][1],
                "found": a["planted_found"],
                "total": a["planted_total"],
                "genuine": a["genuine_unplanted"],
                "fp": a["false_positives"],
                "cost": f"{a['claude_cost_usd']:.2f}",
                "tests": sum(a["results"].values()),
            }
        )
    t = bench["totals"]
    return {
        "apps": apps,
        "totals": {
            "found": t["planted_found"],
            "total": t["planted_total"],
            "rate": round(100 * t["planted_found"] / t["planted_total"]),
            "fp": t["false_positives"],
            "reported": sum(a["bugs_reported"] for a in bench["apps"].values()),
            "cost": f"{t['claude_cost_usd']:.2f}",
        },
        "img": {
            "run_overview": data_uri(SHOTS / "run-overview.png"),
            "site_model": data_uri(SHOTS / "site-model.png"),
            "test_cases": data_uri(SHOTS / "test-cases.png"),
            "live": data_uri(SHOTS / "live-run-viewer.png"),
            "bug": data_uri(SHOTS / "bug-detail.png"),
        },
        "logo": svg_uri(ROOT / "docs" / "assets" / "logo.svg"),
        "author": AUTHOR,
        "role": ROLE,
    }


def thumbnail_html(ctx: dict, width: int, height: int, compact: bool = False) -> str:
    t = ctx["totals"]
    title = 64 if compact else 120
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@500;700;800&display=swap" rel="stylesheet">
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{width:{width}px;height:{height}px;overflow:hidden;font-family:Inter,Arial,sans-serif;
background:radial-gradient({width}px {height}px at 0% 0%,rgba(37,99,235,.45),transparent 60%),#0A0F1C;color:#fff;position:relative}}
.safe{{position:absolute;inset:{height * 0.07:.0f}px {width * 0.06:.0f}px;display:grid;grid-template-columns:{'1fr 1fr' if not compact else '1.05fr 1fr'};gap:{width * 0.03:.0f}px;align-items:center}}
h1{{font-size:{title}px;font-weight:800;letter-spacing:-.04em;line-height:1}} p{{font-size:{title * 0.33:.0f}px;color:#CBD5E1;margin-top:{title * 0.25:.0f}px;line-height:1.3;font-weight:500}}
.badge{{display:inline-block;margin-top:{title * 0.35:.0f}px;background:#16A34A;color:#fff;font-weight:800;font-size:{title * 0.3:.0f}px;padding:{title * 0.12:.0f}px {title * 0.22:.0f}px;border-radius:{title * 0.14:.0f}px}}
.logo{{width:{title * 0.85:.0f}px;height:{title * 0.85:.0f}px;margin-bottom:{title * 0.22:.0f}px}}
.shot{{border-radius:16px;overflow:hidden;border:2px solid rgba(148,163,184,.3);box-shadow:0 30px 90px rgba(0,0,0,.6)}} .shot img{{display:block;width:100%}}</style></head>
<body><div class="safe"><div><img class="logo" src="{ctx['logo']}"><h1>QA Pilot</h1><p>AI that tests your web app and proves every bug</p>
<div class="badge">Found {t['found']} of {t['total']} planted bugs</div></div>
<div class="shot"><img src="{ctx['img']['bug']}"></div></div></body></html>"""


def render(session: BrowserSession, html: str, path: Path, width: int, height: int) -> None:
    tmp = EXPORT / "_render.html"
    tmp.write_text(html, encoding="utf-8")
    session.driver.execute_cdp_cmd(
        "Emulation.setDeviceMetricsOverride",
        {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
    )
    session.navigate(tmp.as_uri())
    session.wait_ready(timeout_s=10)
    session.driver.execute_script("return document.fonts.ready")
    shot = session.driver.execute_cdp_cmd(
        "Page.captureScreenshot",
        {"format": "png", "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": 1}},
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(shot["data"]))
    tmp.unlink()


def to_jpg(png: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    for q in (90, 85, 80):
        Image.open(png).convert("RGB").save(out, "JPEG", quality=q, optimize=True)
        if out.stat().st_size < 2_000_000:
            return


def main() -> int:
    ctx = context()
    env = Environment(loader=FileSystemLoader(str(CS)), autoescape=True)
    html = env.get_template("slides.html.j2").render(**ctx)
    deck = CS / "case-study.html"
    deck.write_text(html, encoding="utf-8")
    print(f"{deck.relative_to(ROOT)} ({deck.stat().st_size // 1024} KB)")

    EXPORT.mkdir(parents=True, exist_ok=True)
    problems = []
    with BrowserSession(headless=True, width=1600, height=1200) as s:
        s.driver.execute_cdp_cmd(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1600, "height": 1200, "deviceScaleFactor": 1, "mobile": False},
        )
        s.navigate(deck.as_uri())
        s.wait_ready(timeout_s=15)
        s.driver.execute_script("return document.fonts.ready")
        # overflow check: any element whose box leaves its slide
        problems += s.driver.execute_script("""const out = [];
            document.querySelectorAll('.slide').forEach((sl, i) => {
              const r = sl.getBoundingClientRect();
              sl.querySelectorAll('h1,h2,p,li,td,.card,.stage,.window:not(.bleed),.callout,.pill,.tag').forEach(el => {
                const b = el.getBoundingClientRect();
                if (b.width && (b.right > r.right + 1 || b.bottom > r.bottom + 1 || el.scrollWidth > el.clientWidth + 2))
                  out.push(`slide ${i + 1}: ${el.tagName.toLowerCase()}.${el.className} overflows`);
              });
            });
            return out;""")
        tops = s.driver.execute_script(
            "return [...document.querySelectorAll('.slide')].map(e => e.getBoundingClientRect().top + scrollY)"
        )
        slides = EXPORT / "slides"
        slides.mkdir(parents=True, exist_ok=True)
        for i, top in enumerate(tops, 1):
            shot = s.driver.execute_cdp_cmd(
                "Page.captureScreenshot",
                {
                    "format": "png",
                    "captureBeyondViewport": True,
                    "clip": {"x": 0, "y": top, "width": 1600, "height": 1200, "scale": 1},
                },
            )
            (slides / f"slide-{i:02d}.png").write_bytes(base64.b64decode(shot["data"]))
        pdf = s.driver.execute_cdp_cmd(
            "Page.printToPDF",
            {"printBackground": True, "preferCSSPageSize": True, "paperWidth": 16.6667, "paperHeight": 12.5},
        )
        (EXPORT / "QA-Pilot-Case-Study.pdf").write_bytes(base64.b64decode(pdf["data"]))

        up = EXPORT / "upwork"
        render(s, thumbnail_html(ctx, 1600, 1200), up / "00-thumbnail.png", 1600, 1200)
        for n, name in GALLERY:
            (up / f"{name}.png").write_bytes((slides / f"slide-{n:02d}.png").read_bytes())
        for png in sorted(up.glob("*.png")):
            to_jpg(png, up / "jpg" / f"{png.stem}.jpg")
        render(
            s,
            thumbnail_html(ctx, 1280, 640, compact=True),
            EXPORT / "social" / "github-social-preview.png",
            1280,
            640,
        )
        render(
            s,
            thumbnail_html(ctx, 1200, 675, compact=True),
            EXPORT / "social" / "linkedin-x-post.png",
            1200,
            675,
        )

    expected = {
        **{f"slides/slide-{i:02d}.png": (1600, 1200) for i in range(1, 13)},
        "upwork/00-thumbnail.png": (1600, 1200),
        **{f"upwork/{name}.png": (1600, 1200) for _, name in GALLERY},
        "social/github-social-preview.png": (1280, 640),
        "social/linkedin-x-post.png": (1200, 675),
    }
    for rel, size in expected.items():
        p = EXPORT / rel
        if not p.exists():
            problems.append(f"{rel} missing")
        elif Image.open(p).size != size:
            problems.append(f"{rel} is {Image.open(p).size}, expected {size}")
    for jpg in (EXPORT / "upwork" / "jpg").glob("*.jpg"):
        if jpg.stat().st_size >= 2_000_000:
            problems.append(f"{jpg.name} is {jpg.stat().st_size // 1024} KB (≥ 2 MB)")
    print(f"Exported to {EXPORT.relative_to(ROOT)}: PDF, {len(tops)} slides, Upwork and social images")
    for p in problems:
        print("  ✗", p)
    return 1 if problems or len(tops) != 12 else 0


if __name__ == "__main__":
    sys.exit(main())

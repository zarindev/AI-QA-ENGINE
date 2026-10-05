"""Benchmark QA Pilot against the demo apps' planted bugs — the only source of numbers in the README.

    python scripts/benchmark.py score             # score the latest finished run of each demo app
    python scripts/benchmark.py score --app clinic --run 20261005-001738
    python scripts/benchmark.py full --app rental  # fresh end-to-end run through the CLI, then score it

`full` resets the demo data, then runs exactly what a user would: `cli.py run` (Full Mode, test environment, the
demo accounts), `cli.py review --confirm-rules 0.8 --approve all` (the review step, automated), `cli.py execute`.

Scoring: the engine never sees the answer keys in demo_targets/manifests/. This script gives Claude the answer key
and QA Pilot's bug reports and asks which report (if any) describes each planted bug, and whether each remaining
report is a genuine issue that was not planted or a false positive — always with a one-line reason, written to
docs/benchmarks.json so every match can be checked by hand. `--no-ai` uses a cruder keyword matcher instead.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from pydantic import BaseModel  # noqa: E402

from app.ai.client import AIClient  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.execute.stage import BUGS_FILE, RESULTS_FILE  # noqa: E402
from app.storage.repository import Repository  # noqa: E402
from app.storage.schemas import Bug, BugsDoc, ResultsDoc, Run, TestSuite  # noqa: E402
from app.testdesign.stage import TESTCASES_FILE  # noqa: E402

APPS = {"clinic": "clinic", "rental": "car_rental", "shop": "shop_admin"}
OUT = ROOT / "docs" / "benchmarks.json"
OVERRIDES = (
    ROOT / "docs" / "benchmark_overrides.json"
)  # corrections made by a person after reading the matches
PY = sys.executable


class PlantedMatch(BaseModel):
    planted_id: str
    found: bool
    bug_ids: list[str]
    reason: str


class ExtraBug(BaseModel):
    bug_id: str
    verdict: Literal["genuine", "false_positive", "same_as_planted"]
    reason: str


class Scoring(BaseModel):
    planted: list[PlantedMatch]
    extras: list[ExtraBug]


SYSTEM = (
    "You grade an automated QA tool against an answer key of bugs that were deliberately planted in a demo web app. "
    "For EVERY planted bug decide whether at least one of the tool's bug reports describes the same defect (same "
    "screen or feature AND the same wrong behaviour — a report about a different symptom on the same screen does "
    "not count). List the matching report ids and give a one-line reason. Then, for every report that matched no "
    "planted bug, give a verdict: 'genuine' if it describes a real defect the reports' evidence supports (e.g. "
    "accessibility or layout problems, a real but unplanted inconsistency), 'same_as_planted' if it is a second "
    "report of a planted bug, 'false_positive' if the evidence shows the app behaved correctly or the report rests "
    "on test interference. Be strict and fair."
)


def manifest(app: str) -> dict:
    return json.loads(
        (ROOT / "demo_targets" / "manifests" / f"{APPS[app]}_planted_bugs.json").read_text("utf-8")
    )


def find_run(repo: Repository, url: str, run_id: str | None) -> tuple[str, Run]:
    for p in repo.list_projects():
        if p.url.rstrip("/") != url.rstrip("/"):
            continue
        runs = [repo.get_run(p.slug, run_id)] if run_id else repo.list_runs(p.slug)
        for r in runs:
            if r.status == "completed" and repo.has_run_doc(r, BUGS_FILE):
                return p.slug, r
    raise SystemExit(f"No finished run with bugs for {url}. Run `benchmark.py full` first.")


def _bug_text(b: Bug) -> str:
    return (
        f"{b.id} [{b.severity}, {b.status}, repro {b.reproducibility or '-'}] {b.title}\n"
        f"  summary: {b.summary[:300]}\n  expected: {b.expected[:200]}\n  actual: {b.actual[:250]}\n"
        f"  url: {b.environment.url} · role: {b.environment.role} · category: {b.category}"
    )


def score_ai(m: dict, bugs: list[Bug]) -> Scoring:
    key = "\n".join(
        f"{p['id']} [{p['category']}, expected severity {p['expected_severity']}] {p['title']} — "
        f"{p['description']} (at {p['location']})"
        for p in m["bugs"]
    )
    reports = "\n".join(_bug_text(b) for b in bugs)
    ai = AIClient()
    return ai.structured(
        system=SYSTEM,
        content=f"# Answer key — {m['name']}\n{key}\n\n# The tool's bug reports\n{reports}",
        schema=Scoring,
        purpose="benchmark scoring",
        effort="medium",
        max_tokens=16000,
        use_cache=False,
    )


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", text.lower())}


def score_keywords(m: dict, bugs: list[Bug]) -> Scoring:
    planted, used = [], set()
    for p in m["bugs"]:
        want = _words(p["title"] + " " + p["description"])
        path = re.findall(r"/[a-z_]+", p["location"])
        hits = []
        for b in bugs:
            have = _words(f"{b.title} {b.summary} {b.actual}")
            if len(want & have) >= 3 and (not path or any(x in b.environment.url for x in path)):
                hits.append(b.id)
        used.update(hits)
        planted.append(
            PlantedMatch(planted_id=p["id"], found=bool(hits), bug_ids=hits, reason="keyword overlap")
        )
    extras = [
        ExtraBug(bug_id=b.id, verdict="genuine", reason="unclassified (--no-ai)")
        for b in bugs
        if b.id not in used
    ]
    return Scoring(planted=planted, extras=extras)


def score(repo: Repository, app: str, run_id: str | None, use_ai: bool) -> dict:
    m = manifest(app)
    slug, run = find_run(repo, m["url"], run_id)
    bugs = [b for b in repo.load_run_doc(run, BUGS_FILE, BugsDoc).bugs if b.status != "rejected"]
    results = repo.load_run_doc(run, RESULTS_FILE, ResultsDoc).results
    suite = repo.load_run_doc(run, TESTCASES_FILE, TestSuite)
    s = score_ai(m, bugs) if use_ai else score_keywords(m, bugs)
    overrides = json.loads(OVERRIDES.read_text("utf-8"))["overrides"] if OVERRIDES.exists() else []
    for o in (o for o in overrides if o["app"] == app):
        for p in s.planted:
            if p.planted_id == o["planted_id"]:
                p.found = o["found"]
                p.bug_ids = [] if not o["found"] else p.bug_ids
                p.reason = f"Corrected by review: {o['reason']}"
    shared: dict[str, list[str]] = {}
    for p in s.planted:
        if p.found:
            for i in p.bug_ids:
                shared.setdefault(i, []).append(p.planted_id)
    for bug_id, ids in shared.items():
        if len(ids) > 1:
            print(
                f"  ! {app}: {bug_id} is matched to {', '.join(ids)} — check by hand (docs/benchmark_overrides.json)"
            )
    by_id = {b.id: b for b in bugs}
    found = [p for p in s.planted if p.found and any(i in by_id for i in p.bug_ids)]
    only_review = [
        p.planted_id for p in found if all(by_id[i].status == "needs_review" for i in p.bug_ids if i in by_id)
    ]
    sev_ok = 0
    for p in found:
        expected = next(x["expected_severity"] for x in m["bugs"] if x["id"] == p.planted_id)
        sev_ok += any(by_id[i].severity == expected for i in p.bug_ids if i in by_id)
    counts = {k: sum(1 for r in results if r.result == k) for k in ("pass", "fail", "blocked", "error")}
    index = next((x for x in repo.get_index(slug).runs if x.id == run.id), None)
    browser_minutes = sum(r.duration_ms for r in results) / 60000
    return {
        "app": m["name"],
        "domain": m["domain"],
        "project": slug,
        "run": run.id,
        "mode": run.mode,
        "model": get_settings()["ai"]["model"],
        "pages_explored": index.pages if index else None,
        "test_cases_approved": sum(1 for c in suite.cases if c.status == "approved"),
        "results": counts,
        "bugs_reported": len(bugs),
        "planted_total": len(m["bugs"]),
        "planted_found": len(found),
        "detection_rate": round(len(found) / len(m["bugs"]), 3),
        "found": sorted(p.planted_id for p in found),
        "found_only_in_needs_review": sorted(only_review),
        "missed": sorted(p.planted_id for p in s.planted if p not in found),
        "severity_agreement": f"{sev_ok}/{len(found)}",
        "genuine_unplanted": sum(1 for e in s.extras if e.verdict == "genuine"),
        "duplicates_of_planted": sum(1 for e in s.extras if e.verdict == "same_as_planted"),
        "false_positives": sum(1 for e in s.extras if e.verdict == "false_positive"),
        "quality_score": index.quality_score if index else None,
        "claude_cost_usd": round(run.token_usage.cost_usd, 2),
        "browser_minutes": round(browser_minutes, 1),
        "scored_with": ("claude" if use_ai else "keywords")
        + (" + human review" if any(o["app"] == app for o in overrides) else ""),
        "matches": [p.model_dump() for p in s.planted],
        "extras": [e.model_dump() for e in s.extras],
    }


def _cli(*args: str) -> None:
    cmd = [PY, str(ROOT / "backend" / "cli.py"), *args]
    print("$", " ".join(a if " " not in a else repr(a) for a in cmd[1:]))
    subprocess.run(cmd, check=True, cwd=ROOT / "backend")


def full(app: str) -> None:
    """A fresh end-to-end run, exactly as a user would drive it (review step automated)."""
    m = manifest(app)
    subprocess.run([PY, str(ROOT / "scripts" / "seed_demo.py"), app], check=True)
    roles = [f"{r}:{u}:{p}" for r, (u, p) in m["roles"].items()]
    _cli(
        "run",
        m["url"],
        "--name",
        m["name"],
        "--env",
        "test",
        "--mode",
        "full",
        "--confirm-full-mode",
        "--i-am-authorized",
        "--authorized-by",
        "benchmark.py",
        *[x for r in roles for x in ("--role", r)],
    )
    slug = Repository().list_projects()
    target = next(p.slug for p in slug if p.url.rstrip("/") == m["url"].rstrip("/"))
    _cli("review", target, "--confirm-rules", "0.8", "--approve", "all")
    _cli("execute", target)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["score", "full"])
    ap.add_argument("--app", choices=list(APPS), action="append", help="default: all three")
    ap.add_argument("--run", help="run id to score (with a single --app)")
    ap.add_argument("--no-ai", action="store_true", help="keyword matching instead of Claude")
    args = ap.parse_args()
    apps = args.app or list(APPS)
    if args.command == "full":
        for a in apps:
            started = time.time()
            full(a)
            print(f"{a}: finished in {(time.time() - started) / 60:.0f} min")
    repo = Repository()
    use_ai = not args.no_ai and AIClient.available()
    previous = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {"apps": {}}
    for a in apps:
        res = score(repo, a, args.run if len(apps) == 1 else None, use_ai)
        previous["apps"][a] = res
        print(
            f"{res['app']}: {res['planted_found']}/{res['planted_total']} planted bugs found "
            f"({res['detection_rate']:.0%}), {res['genuine_unplanted']} other genuine, "
            f"{res['false_positives']} false positives, ${res['claude_cost_usd']}, missed {', '.join(res['missed']) or '—'}"
            + (
                f", only in Needs review: {', '.join(res['found_only_in_needs_review'])}"
                if res["found_only_in_needs_review"]
                else ""
            )
        )
    apps_all = previous["apps"].values()
    previous["generated_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    previous["totals"] = {
        "planted_total": sum(x["planted_total"] for x in apps_all),
        "planted_found": sum(x["planted_found"] for x in apps_all),
        "false_positives": sum(x["false_positives"] for x in apps_all),
        "genuine_unplanted": sum(x["genuine_unplanted"] for x in apps_all),
        "claude_cost_usd": round(sum(x["claude_cost_usd"] for x in apps_all), 2),
    }
    t = previous["totals"]
    t["detection_rate"] = round(t["planted_found"] / t["planted_total"], 3) if t["planted_total"] else None
    previous["method"] = (
        "Each demo app was explored and tested end to end by QA Pilot (Full Mode, test environment, demo "
        "accounts; business rules with confidence ≥ 0.8 confirmed and all designed test cases approved — the "
        "review step a person would do). Reports were matched to the planted-bug answer key by "
        + (
            "Claude with a stated reason per match (see `matches` / `extras`)."
            if use_ai
            else "keyword overlap."
        )
    )
    OUT.write_text(json.dumps(previous, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

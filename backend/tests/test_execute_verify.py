from __future__ import annotations

import io
import subprocess
from types import SimpleNamespace

import imageio_ffmpeg
from PIL import Image

from app.execute import media
from app.execute.agent import TOOLS, case_brief
from app.execute.replayer import script_from
from app.execute.runner import resolve_role
from app.storage.schemas import (
    Bug,
    Execution,
    LocatorSet,
    Project,
    Role,
    Run,
    StepResult,
    TestCase,
    utcnow,
)
from app.verify import bugs as bugbuilder


def _png(w=1440, h=900, colour=(240, 240, 240)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, "PNG")
    return buf.getvalue()


def test_annotation_draws_box_and_caption():
    out = media.annotate(
        _png(),
        {"x": 100, "y": 100, "width": 200, "height": 40},
        "BUG-001: expected 60.00 — actual 120.00",
        1440,
    )
    img = Image.open(io.BytesIO(out)).convert("RGB")
    assert img.size == (1440, 900)
    assert img.getpixel((94, 120)) == media.RED  # left edge of the box (6px padding)
    assert img.getpixel((4, 890))[0] > 150  # red accent of the caption bar
    plain = Image.open(io.BytesIO(media.annotate(_png(), None, "no box", 1440))).convert("RGB")
    assert plain.getpixel((300, 300)) == (240, 240, 240)


def test_video_and_clip_are_valid_mp4(tmp_path):
    frames = []
    for i in range(3):
        p = tmp_path / f"f{i}.jpg"
        p.write_bytes(media.to_jpeg(_png(colour=(30 * i, 80, 120))))
        frames.append((p, f"Step {i + 1}"))
    video = media.build_video(frames, tmp_path / "v.mp4", seconds_per_frame=1.0)
    ann = tmp_path / "a.png"
    ann.write_bytes(media.annotate(_png(), None, "x", 1440))
    clip = media.build_clip(frames, ann, tmp_path / "c.mp4")
    for f, seconds in ((video, 3), (clip, 10)):
        info = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(f)], capture_output=True, text=True
        ).stderr
        dur = info.split("Duration: ")[1].split(",")[0]
        h, m, s = dur.split(":")
        assert abs(float(s) + int(m) * 60 - seconds) < 1.5, info
    assert media.build_video([], tmp_path / "none.mp4") is None


def test_agent_tools_are_strict_and_carry_a_note():
    names = {t["name"] for t in TOOLS}
    assert {"click", "type", "select", "navigate", "assert", "finish"} <= names
    for t in TOOLS:
        schema = t["input_schema"]
        assert t["strict"] and schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"]) and "note" in schema["required"]
    brief = case_brief(TestCase(id="TC-1", title="t", test_data={"fee": "120"}), "doctor", "http://x.test")
    assert "logged in as doctor" in brief and '"fee": "120"' in brief


def test_role_resolution():
    p = Project(
        slug="p",
        name="p",
        url="http://x.test",
        authorized_by="a",
        authorized_at=utcnow(),
        roles=[Role(name="receptionist"), Role(name="admin")],
    )
    assert resolve_role(p, "Receptionist") == "receptionist"
    assert resolve_role(p, "admins") == "admin"
    assert resolve_role(p, "signed out") == "public"
    assert resolve_role(p, "nurse") == ""


def test_replay_script_keeps_actions_and_checks():
    case = TestCase(id="TC-1", title="t", expected_result="Total is 60.00")
    loc = LocatorSet(id="save")
    ex = Execution(
        test_case_id="TC-1",
        result="fail",
        role="admin",
        steps=[
            StepResult(order=1, action="navigate", input="/patients/new", url="http://x.test/patients/new"),
            StepResult(order=2, action="type", input="QAP_A", locators=loc, target="[3] input"),
            StepResult(order=3, action="click", locators=loc, result="blocked"),
            StepResult(order=4, action="assert", target="Patient pays 60.00", result="fail"),
        ],
    )
    script = script_from(case, ex)
    assert [s.action for s in script.steps] == ["navigate", "type"]
    assert script.checks == ["Patient pays 60.00"] and script.role == "admin"


def _exec(result, steps, method="agent", conf=0.9, role="doctor"):
    return Execution(
        test_case_id="TC-1",
        result=result,
        method=method,
        confidence=conf,
        role=role,
        steps=steps,
        failure_step=steps[-1].order if result == "fail" else None,
    )


def test_rule_bugs_group_permission_holes_across_roles():
    run = Run(id="r", project_slug="p")

    def step() -> StepResult:
        return StepResult(
            order=1,
            action="navigate",
            target="/reports",
            url="http://x/reports",
            result="fail",
            observation="The page opened",
            screenshot_after="a.jpg",
        )

    f1 = bugbuilder.Failure(
        TestCase(id="TC-REP-001", title="t", technique="permission", module="Report"),
        [_exec("fail", [step()], "rule", role="doctor")] * 3,
    )
    f2 = bugbuilder.Failure(
        TestCase(id="TC-REP-002", title="t", technique="permission", module="Report"),
        [_exec("fail", [step()], "rule", role="receptionist")] * 3,
    )
    drafts = bugbuilder.rule_bugs([f1, f2], run)
    assert len(drafts) == 1
    bug = drafts[0].bug
    assert bug.severity == "critical" and bug.test_case_ids == ["TC-REP-001", "TC-REP-002"]
    assert "Also reproduced as receptionist" in bug.actual and bug.reproducibility == "3/3"


def test_flaky_and_low_confidence_go_to_review(repo):
    f = bugbuilder.Failure(
        TestCase(id="TC-1", title="t"),
        [
            _exec("fail", [StepResult(order=1, action="assert", result="fail")], conf=0.9),
            _exec("pass", [StepResult(order=1, action="assert")]),
            _exec("pass", [StepResult(order=1, action="assert")]),
        ],
    )
    assert f.reproducibility == "1/3"
    draft = bugbuilder.agent_bug(None, f, Run(id="r", project_slug="p"))
    run = (
        repo.create_run(Run(id="r", project_slug="p"))
        if repo.list_projects()
        else Run(id="r", project_slug="p")
    )
    bugs = bugbuilder.finalize(repo, run, [draft])
    assert bugs[0].status == "needs_review" and bugs[0].confidence < 0.6 and bugs[0].id == "BUG-001"


def test_dedupe_merges_same_symptom_and_ai_groups():
    def draft(title, key, sev="minor", tc="TC-1", source="test"):
        return bugbuilder.BugDraft(
            Bug(
                id="",
                title=title,
                severity=sev,
                symptom_key=key,
                test_case_ids=[tc],
                links={"test_cases": [tc]},
                source=source,
                category="js_error",
            )
        )

    a = draft("JS error on /appointments", "js:/appointments", "minor", "TC-1")
    b = draft("JS error on /appointments (crawl)", "JS:/appointments", "major", "", "automatic_check")
    c = draft("Another bug", "other", "minor", "TC-9")
    out = bugbuilder.dedupe([a, b, c], ai=None)
    assert len(out) == 2
    merged = next(d for d in out if d.bug.symptom_key.startswith("js"))
    assert merged.bug.severity == "major" and "Raised to major" in merged.bug.severity_reason

    fake_ai = SimpleNamespace(structured=lambda **kw: bugbuilder.DedupeGroups(groups=[[0, 1]]))
    out2 = bugbuilder.dedupe([draft("x", "k1", tc="TC-1"), draft("y", "k2", tc="TC-2")], fake_ai)
    assert len(out2) == 1 and out2[0].bug.test_case_ids == ["TC-1", "TC-2"]


def test_money_failures_escalate_and_priority_never_below_severity():
    sev, note = bugbuilder._escalate("minor", "Invoice total ignores VAT")
    assert sev == "major" and "money" in note
    assert bugbuilder._priority(Bug(id="b", title="t", severity="critical", priority="P3")) == "P1"
    assert bugbuilder._priority(Bug(id="b", title="t", severity="trivial", priority="P2")) == "P2"

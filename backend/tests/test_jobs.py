from __future__ import annotations

import time
from datetime import timedelta

from app.jobs.run_state import RunTracker, heartbeat, mark_interrupted_runs
from app.storage.schemas import Project, Run, utcnow


def _running(repo, run_id: str, beat_age_s: int) -> Run:
    run = repo.create_run(Run(id=run_id, project_slug="p", status="running", started_at=utcnow()))
    run.heartbeat_at = utcnow() - timedelta(seconds=beat_age_s)
    repo.save_run(run)
    return run


def test_only_runs_with_a_stale_heartbeat_are_marked_interrupted(repo):
    repo.create_project(
        Project(slug="p", name="p", url="http://x.test", authorized_by="t", authorized_at=utcnow())
    )
    _running(repo, "live", 10)  # another QA Pilot process is still working on it
    _running(repo, "dead", 600)
    marked = {r.id for r in mark_interrupted_runs(repo)}
    assert marked == {"dead"}
    assert repo.get_run("p", "live").status == "running"
    assert repo.get_run("p", "dead").status == "interrupted"


def test_heartbeat_keeps_a_quiet_run_fresh(repo):
    repo.create_project(
        Project(slug="p", name="p", url="http://x.test", authorized_by="t", authorized_at=utcnow())
    )
    run = _running(repo, "r", 600)
    tracker = RunTracker(repo, run)
    with heartbeat(tracker, every_s=0.05):
        time.sleep(0.3)
    assert (utcnow() - repo.get_run("p", "r").heartbeat_at).total_seconds() < 5

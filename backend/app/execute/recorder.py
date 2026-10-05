"""Per-test recording: step screenshots, console + network logs, automatic findings, video at the end."""

from __future__ import annotations

import json
from pathlib import Path

from app.browser.driver import BrowserSession
from app.execute import media, privacy
from app.explore.checks import _same_site
from app.storage.repository import Repository
from app.storage.schemas import AutoFinding, ConsoleEntry, NetworkEvent, Run, StepResult

_IGNORED_CONSOLE = ("favicon.ico", "Failed to load resource")


class Recorder:
    def __init__(
        self, repo: Repository, run: Run, session: BrowserSession, case_id: str, attempt: int, site_host: str
    ) -> None:
        self.repo = repo
        self.run = run
        self.session = session
        self.base = f"artifacts/executions/{case_id}/attempt-{attempt}"
        self.site_host = site_host
        self.last_shot = ""
        self.last_png = b""
        self.frames: list[tuple[str, str]] = []
        self.console: list[ConsoleEntry] = []
        self.network: list[NetworkEvent] = []
        self.findings: list[AutoFinding] = []

    def current_png(self) -> bytes:
        return self.capture(0)

    def capture(self, step: int) -> bytes:
        """Screenshot after a step (also the 'before' of the next step), plus the logs produced by the step."""
        png = self.session.screenshot_png()
        rel = f"{self.base}/step-{step:02d}.jpg"
        path = self.repo.run_path(self.run, rel)
        self.repo.write_bytes(path, media.to_jpeg(png))
        rects = privacy.pii_rects(self.session.driver)
        if rects:
            self.repo.write_text(privacy.sidecar(path), json.dumps(rects))
        self.last_shot, self.last_png = rel, png
        self._drain(step)
        return png

    def note_step(self, step: StepResult) -> None:
        caption = f"{step.order}. {step.action} {step.target}".strip()
        if step.input:
            caption += f" ← “{step.input[:60]}”"
        self.frames.append((step.screenshot_after, caption[:150]))

    def _drain(self, step: int) -> None:
        console, network = self.session.drain()
        self.console += console
        self.network += network
        url = self.session.current_url
        for entry in console:
            if entry.level == "error" and not any(x in entry.message for x in _IGNORED_CONSOLE):
                self.findings.append(
                    AutoFinding(
                        check="js_error",
                        severity="minor",
                        title="JavaScript error",
                        detail=entry.message[:400],
                        url=url,
                        step=step,
                    )
                )
        for event in network:
            if not _same_site(event.url, self.site_host) or event.url.endswith("favicon.ico"):
                continue
            if event.status and event.status >= 500:
                self.findings.append(
                    AutoFinding(
                        check="server_error",
                        severity="major",
                        title=f"HTTP {event.status}",
                        detail=f"{event.method} {event.url}",
                        url=url,
                        step=step,
                    )
                )

    def finish(self, title: str, blur: bool = False) -> dict[str, str]:
        """Write logs and the test video; returns the relative paths."""
        out: dict[str, str] = {}
        logs = {
            "console": [c.model_dump() for c in self.console],
            "network": [n.model_dump() for n in self.network],
        }
        for name, data in logs.items():
            rel = f"{self.base}/{name}.json"
            self.repo.write_text(self.repo.run_path(self.run, rel), json.dumps(data, indent=2))
            out[name] = rel
        frames = [(self.repo.run_path(self.run, p), c) for p, c in self.frames]
        if frames:
            frames.insert(0, (frames[0][0], title[:150]))
            video = media.build_video(
                frames,
                self.repo.run_path(self.run, f"{self.base}/video.mp4"),
                seconds_per_frame=1.5,
                load=privacy.blurred_bytes if blur else None,
            )
            if video:
                out["video"] = f"{self.base}/video.mp4"
        return out

    def frame_paths(self) -> list[tuple[Path, str]]:
        return [(self.repo.run_path(self.run, p), c) for p, c in self.frames]

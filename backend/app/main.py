"""QA Pilot server: JSON API under /api, the committed React build at /, everything on localhost.

python -m uvicorn app.main:app --port 8000      (start.bat / start.sh do this for you)
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import demo, execution, insights, projects, review, runs, settings
from app.api.deps import executor, repo
from app.core.logging import get_logger, setup_logging
from app.core.paths import STATIC_DIR
from app.jobs.run_state import mark_interrupted_runs

log = get_logger("server")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging(log_file=repo().root / "logs" / "qa-pilot.log")
    marked = mark_interrupted_runs(repo())
    if marked:
        log.info("Marked %d unfinished run(s) from a previous session as interrupted", len(marked))
    yield
    executor().shutdown()
    demo.stop_demo_processes()


app = FastAPI(title="QA Pilot", version=__version__, lifespan=lifespan)
# Dev mode only: the Vite dev server on :5173 calls the API on :8000.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
for router in (
    settings.router,
    projects.router,
    runs.router,
    review.router,
    execution.router,
    insights.router,
    demo.router,
):
    app.include_router(router)


if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    """Serve the single-page app; unknown non-API paths fall back to index.html for client-side routing."""
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    candidate = (STATIC_DIR / path).resolve()
    if path and STATIC_DIR.resolve() in candidate.parents and candidate.is_file():
        return FileResponse(candidate)
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        {"detail": "The UI is not built. Run scripts/build_frontend.(bat|sh) or use the API at /docs."},
        status_code=503,
    )

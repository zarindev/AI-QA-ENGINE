# QA Pilot — build progress

Source of truth for what is done. Each phase ends with tests green, a real run against live targets,
an update here, and a commit (`feat(phase-N): ...`).

## Plan

| Phase | Scope | Status |
|---|---|---|
| 1. Foundation + Explore | Scaffold, config, file storage layer + tests, Claude client, Chrome driver + CDP logs, DOM snapshot, locators, login (credentials / manual session), crawler (public + per role + SPA click discovery), automatic checks, run state, CLI, basic HTML report | **Done** |
| 2. Understand + Site Model | Classifier, Domain Packs, model builder (NetworkX), FastAPI + React shell, SSE, job executor, onboarding, Site Profile + Site Model screens, setup/start scripts, committed static build, **3 demo apps** | Next |
| 3. Requirements + Test Design | Stories, workflows, rules + confirm flow, generator, test data, review UI, requirements PDF, Excel test cases, Gherkin | — |
| 4. Execute + Verify | Agent loop, actions, recorder, replayer, self-healing, judge, re-runs, severity, dedupe, clips, annotated screenshots, Live Run Viewer, Results + Bugs | — |
| 5. Advanced checks | Permission matrix, data integrity, business rules, multi-viewport, axe, quality score, heatmap, regression, Bug Replay, privacy blur | — |
| 6. Reporting | All exports (Excel, PDFs, CSV, Gherkin, pytest suite, traceability) | — |
| 7. Public repo polish | README, CONTRIBUTING, SECURITY, TROUBLESHOOTING, CI, templates, fresh-clone test, pre-commit secret check | — |
| 8. Showcase package | Benchmarks, screenshots, samples, case study, Upwork + social images | — |

## Phase 1 — Foundation + Explore (done)

**Built**
- `backend/app/core`: settings (YAML defaults + `workspace/settings.json` overrides + `.env`), paths, logging
  with secret redaction, Fernet crypto (key auto-generated into `.env`), Safe Mode guard.
- `backend/app/storage`: Pydantic models for every file (Section 5), file repository (atomic temp-file +
  `os.replace` writes, per-file thread + `filelock` locks, encrypted secrets, run folders, per-project
  `index.json`), schema migrations framework.
- `backend/app/ai/client.py`: Claude client (`claude-sonnet-5-5` by default) — strict JSON via
  `beta.messages.parse` + Pydantic, adaptive thinking, effort from settings, prompt caching on the system
  prompt, server-side refusal fallbacks (`fallbacks: "default"`), local response cache, token budget,
  cost tracking.
- `backend/app/browser`: Chrome session (Selenium Manager, CDP network + console capture, eager loading with a
  network-aware readiness wait, alert auto-dismiss, session export/import), DOM snapshot with indexed
  elements (`[12] button "Save"`) and locator sets, multi-strategy locator lookup, login (heuristics → Claude
  fallback; manual session capture for 2FA/SSO).
- `backend/app/explore`: URL normalization/templating/scope, BFS crawler (public first, then each role;
  SPA click discovery; template instance limit; re-login on session loss; per-page recovery and browser
  restart), automatic checks (HTTP errors, JS errors, failed first/third-party requests, broken images,
  broken links (404/410/5xx only), slow pages, timeouts, horizontal overflow, mixed content, visible error
  text), de-duplication by root symptom.
- `backend/app/jobs/run_state.py`: run lifecycle in `run.json`, weighted progress, events in
  `artifacts/logs/events.jsonl`, interrupted-run detection.
- `backend/app/reports/html_basic.py`: dark HTML crawl report.
- `backend/cli.py`: `run`, `projects`, `runs`, `report`.

**Verified against live targets (Safe Mode, no API key — heuristics only)**

| Target | Result |
|---|---|
| saucedemo.com (3 roles) | `standard_user` + `problem_user` logged in; `locked_out_user` correctly reported as failed with the site's message; inventory, product, cart pages found (cart via click discovery); Logout / Reset App State / Checkout blocked by Safe Mode |
| the-internet.herokuapp.com | 60 pages; found the JS-error page, broken images, horizontal overflow on `/large`, intentional 404 links, 401 basic-auth pages (trivial), third-party failures (trivial) |
| opensource-demo.orangehrmlive.com (Admin) | Logged in to the Vue SPA, 25 admin pages across all modules; `purgeEmployee` blocked |
| automationexercise.com | 20 public pages in 3.5 min; one de-duplicated mixed-content finding across 19 pages (HTTP stylesheet on HTTPS); API-page "DELETE" buttons and "Logout" blocked. An earlier run also saw a 488px horizontal overflow on many pages (likely ad iframes; not reproduced on the re-run) |

**Tests:** 59 passing (`pytest`), including a real-Chrome crawl of a local fixture site (login, re-login,
Safe Mode, SPA click discovery, checks, no credentials on disk). `ruff`, `black`, `mypy` clean.

**Not yet verified:** Claude-backed code paths (login fallback) — no `ANTHROPIC_API_KEY` was available
in this session. Unit tests cover the request shape, caching, budget and refusal handling.

## How to resume

```
Continue QA_PILOT_BUILD_PROMPT.md from Phase 2. Check git log and docs/PROGRESS.md for what's done.
```

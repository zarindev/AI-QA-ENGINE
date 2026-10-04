# QA Pilot — build progress

Source of truth for what is done. Each phase ends with tests green, a real run against live targets,
an update here, and a commit (`feat(phase-N): ...`).

## Plan

| Phase | Scope | Status |
|---|---|---|
| 1. Foundation + Explore | Scaffold, config, file storage layer + tests, Claude client, Chrome driver + CDP logs, DOM snapshot, locators, login (credentials / manual session), crawler (public + per role + SPA click discovery), automatic checks, run state, CLI, basic HTML report | **Done** |
| 2. Understand + Site Model | Classifier, Domain Packs, model builder (NetworkX), FastAPI + React shell, SSE, job executor, onboarding, Site Profile + Site Model screens, setup/start scripts, committed static build, **3 demo apps** | **Done** (AI path awaiting a key) |
| 3. Requirements + Test Design | Stories, workflows, rules + confirm flow, generator, test data, review UI, requirements PDF, Excel test cases, Gherkin | Next |
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

## Phase 2 — Understand + Site Model (done)

**Built**
- **Demo targets** (`demo_targets/`): CarePoint Clinic (:8101, admin/doctor/receptionist), DriveNow Rentals
  (:8102, admin/agent/customer), StockRoom POS (:8103, admin/cashier). Flask + Jinja, JSON-file storage, reset route,
  seed dates relative to today, launchers for Windows and POSIX. **15 planted bugs each** across 10 categories, with
  manifests (never read by the engine) and a regression test that proves every planted bug is present.
- **Understand**: crawl summarizer (screens by URL template, forms with validation attributes, tables, actions,
  navigation menu per role); Claude classifier with strict JSON schema + screenshots; offline heuristic classifier
  driven by **12 Domain Packs** (healthcare, rental, ecommerce, education, hr, crm, restaurant, real_estate,
  banking, booking, portfolio, blog).
- **Site Model**: NetworkX knowledge graph (roles, modules, features, pages, entities, fields and their relations),
  node-link JSON, React Flow export with column/grid layout.
- **Server**: FastAPI app serving the committed UI build; projects (authorization record, encrypted credentials,
  manual-login capture), runs (start / cancel / resume, Full Mode rules), run data, artifact files (path-safe), SSE
  live events with history replay, settings + API-key onboarding, "Try with a demo app"; job executor + event bus;
  interrupted runs detected on startup.
- **UI** (React 19, Vite 8, Tailwind 4, shadcn-style components, TanStack Query, React Flow, Framer Motion):
  onboarding, projects, 6-step new-project wizard, project detail (runs, roles, manual login, delete), run overview
  (8-stage stepper, live screenshot stream, narration, pages / findings / Safe Mode tabs), site profile, knowledge
  graph, settings; Ctrl+K command palette; dark/light themes; loading, empty and error states.
- **Scripts**: `setup.bat/.sh`, `start.bat/.sh` (free-port fallback, opens the browser), `build_frontend.bat/.sh`.
- The CLI now runs the same pipeline as the UI (explore → understand → model → report).

**Verified**
- Demo apps classified correctly by the heuristic classifier: clinic → healthcare (0.75), car rental → rental (0.73),
  shop → ecommerce (0.75). Also saucedemo → ecommerce, OrangeHRM → hr, automationexercise → ecommerce, and the
  the-internet test playground → `other` (7/7).
- "Try with a demo app" end-to-end in the real UI: 41 pages across 4 roles, healthcare profile, 16-screen graph.
- Explore alone already catches clinic CL-10 (broken privacy link) and CL-11 (JS error).
- 78 Python tests (incl. an end-to-end API run in real Chrome and SSE), 4 Vitest tests; ruff, black, mypy, tsc,
  eslint clean.

**Not verified:** the Claude classifier (no API key in this session) — see KNOWN_ISSUES.

## How to resume

```
Continue QA_PILOT_BUILD_PROMPT.md from Phase 3. Check git log and docs/PROGRESS.md for what's done.
```

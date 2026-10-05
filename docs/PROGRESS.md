# QA Pilot — build progress

Source of truth for what is done. Each phase ends with tests green, a real run against live targets,
an update here, and a commit (`feat(phase-N): ...`).

## Plan

| Phase | Scope | Status |
|---|---|---|
| 1. Foundation + Explore | Scaffold, config, file storage layer + tests, Claude client, Chrome driver + CDP logs, DOM snapshot, locators, login (credentials / manual session), crawler (public + per role + SPA click discovery), automatic checks, run state, CLI, basic HTML report | **Done** |
| 2. Understand + Site Model | Classifier, Domain Packs, model builder (NetworkX), FastAPI + React shell, SSE, job executor, onboarding, Site Profile + Site Model screens, setup/start scripts, committed static build, **3 demo apps** | **Done** |
| 3. Requirements + Test Design | Stories, workflows, rules + confirm flow, generator, test data, review UI, requirements PDF, Excel test cases, Gherkin | **Done** |
| 4. Execute + Verify | Agent loop, actions, recorder, replayer, self-healing, judge, re-runs, severity, dedupe, clips, annotated screenshots, Live Run Viewer, Results + Bugs | **Built** — full demo runs paused (API credits ran out) |
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

**Claude classifier, verified on 2026-10-05** (`claude-sonnet-5-5`, real API):

| Demo app | Claude | Offline heuristic |
|---|---|---|
| CarePoint Clinic | healthcare · clinic management, 0.97 | healthcare, 0.75 |
| DriveNow Rentals | rental · car rental back office, 0.97 | rental, 0.73 |
| StockRoom POS | ecommerce · retail point of sale, 0.88 | ecommerce, 0.75 |

Claude also found entities the heuristic missed (Customer, Sale line item), required fields and the insurance
billing rule. Cost for the three classifications: $0.13 (about 4 cents per site).

## Phase 3 — Requirements + Test Design (done)

**Built**
- **Requirements** (`app/requirements`): Claude reverse-engineers user stories with acceptance criteria, workflows as
  ordered steps + state machines (allowed *and* must-be-refused transitions) and business rules with a testable
  condition, category, source and confidence, reading the site profile, every screen and the full text of help /
  terms pages. Offline fallback derives stories from entities, states from status dropdowns and rules from form
  attributes + the domain pack. Rules start `proposed`; only confirmed (or edited) rules drive business-rule tests.
- **Test design** (`app/testdesign`): rules-based generator from what the crawl saw (smoke per role, required
  fields, boundary values and equivalence classes from HTML constraints and field types, CRUD create, direct-URL
  permission checks per role, signed-out access, responsive, accessibility) + Claude for e2e workflows, state
  transitions, business rules (with computed expected values), data integrity, domain negatives and data-level
  permissions. Ids `TC-<MOD>-NNN`, priorities P1–P4, traceability links, `requires_full_mode` flag. Regeneration
  keeps approved, edited and hand-written cases. Plain-English authoring. Cost/time estimate.
- **Test data**: Faker, deterministic, `QAP_` names, `@example.test` emails, 555-01xx phones; boundary probes and
  invalid classes. No personal data in titles (record pages are named from the URL).
- **Exports**: Reverse-Engineered Requirements Document (Markdown + PDF printed by Chrome), Excel workbook (Test
  Cases, User Stories, Business Rules, About — styled, filters, frozen headers), Gherkin `.feature` files (zip).
- **API + UI**: Requirements screen (rules Confirm / Edit / Reject, bulk-confirm ≥ 80 %, stories, workflow state
  diagrams), Test Cases screen (filters, grouped table, bulk approve/skip, side-panel editor with steps, plain
  English, regenerate, estimate, exports).
- Claude client streams large structured responses (SDK refuses non-streaming requests above ~21k tokens).

**Verified on the demo apps with Claude (Full Mode, test environment, 2026-10-05)**

| App | Stories / workflows / rules | Rules confirmed (≥ 80 %) | Approved cases | AI cost (explore → design + regenerate) |
|---|---|---|---|---|
| CarePoint Clinic | 11 / 4 / 27 | 19 | 71 | $0.38 |
| DriveNow Rentals | 12 / 3 / 25 | 16 | 60 | $0.33 |
| StockRoom POS | 14 / 3 / 28 | 20 | 63 | $0.35 |

Without seeing the manifests, Claude proposed rules matching most planted clinic bugs (double booking,
insurance billing, admin-only reports and doctors, phone format, future birth date, inactive doctors, cancelled
visits). The suites were bulk-approved through the API to meet the phase goal; a person would normally review
them first. Estimated cost to *execute* all approved cases: $4–6 per app (Phase 4).

**Tests:** 91 Python tests (incl. review API flow, Excel/Gherkin/PDF exports), 4 Vitest tests.

## Phase 4 — Execute + Verify (built; full runs to finish)

**Built**
- **Browser agent** (`app/execute/agent.py`): observe → decide → act, one strict tool call per Claude turn (click, type,
  select, check, upload, navigate, scroll, wait_for, read, assert, finish). Each turn is self-contained (test case in a
  cached block + compact history + indexed element list + screenshot); a required working-memory `note` on every
  tool call keeps the plan across turns; loop detection nudges the agent. Limits: steps, time, uncached tokens, cost.
- **Actions** (`actions.py`): every action passes the Safe Mode guard (submit buttons judged by their form); Full Mode
  auto-accepts `confirm()` so delete/complete flows can be tested.
- **Rule runner** (`rule_runner.py`, no AI): smoke, direct-URL permission checks, responsive overflow at 768/390 px,
  axe-core accessibility (bundled `axe.min.js`).
- **Recording**: JPEG step screenshots, console + network logs, automatic findings during tests, captioned MP4 per
  test (bundled ffmpeg). **Replay scripts** with multi-strategy locators; replay + one judgement call re-verifies
  failures; a broken locator hands over to the agent (self-healing).
- **Verify** (`app/verify/bugs.py`): re-runs (default 2×) → reproducibility, flaky → "Needs review"; Claude writes each
  agent bug report (title, numbered steps with data, expected / actual, severity + reasoning, priority, symptom key);
  rule failures grouped into templated bugs; exploration findings become bugs; de-duplication by symptom key + one
  Claude grouping pass; annotated screenshot (box on the evidence element) and 10–25 s bug clip.
- **Execution** is resumable (finished tests are kept, errors retried) and stops at once when the API key is missing
  or the account has no credits.
- **UI**: Run approved tests, Live Run Viewer (live agent screenshots, narration, ✓/✗ ticker), Results (per-test
  attempts, step timeline with screenshots, video), Bugs (severity board / table, Needs-review queue), Bug detail
  (all fields, annotated screenshot, clip, video, logs, status, one-click Replay in a visible browser).

**Verified on the demo apps (2026-10-05, before the API credits ran out)**

| App | Tests run | Planted bugs confirmed so far | Other real bugs | False positives |
|---|---|---|---|---|
| CarePoint Clinic | 32 of 71 | 9 of 15: CL-01, 02, 03, 04, 09, 10, 11, 12, 13 | empty-filter counter, dashboard count mismatch | 1 (parallel-test data) |
| DriveNow Rentals | 20 of 60 | 4 of 15: CR-01, 04, 07, 13 | colour contrast | 0 |
| StockRoom POS | 0 of 63 | — | — | — |

Example: the agent registered a 50 %-coverage patient, booked and completed a visit and reported
“patient pays $120.00, expected $60.00” (CL-02), reproduced 3/3, critical, with annotated screenshot and clip.
Agent cost ≈ $0.08–0.15 per test; replay re-runs ≈ $0.03.

**To finish Phase 4:** add API credits, then resume the three runs (`POST …/execute {"resume": true}`) and record the
final per-app numbers. Benchmarks for the README come from Phase 8 only.

## Phase 5 — Advanced checks (built)

- **Quality Score** with sub-scores and documented formula (docs/ARCHITECTURE.md), stored per run, shown in the run list.
- **Coverage heatmap**, **Permission matrix** (holes highlighted, evidence on hover), **Regression comparison**
  (new / fixed / still open / reappeared vs. any earlier run) — screen *Coverage & quality* and *Permission matrix*.
- **Business-rule recalculation** in Python (safe AST evaluator) for tests linked to confirmed rules; the result is
  shown in each attempt.
- **Privacy blur** (Auto / On / Off per project) for bug screenshots, clips, videos and exports.
- **Multi-viewport runs** (desktop / tablet / phone picker next to *Run approved tests*).
- API: `GET …/quality`, `GET …/permissions`, `GET …/compare?base=`, `PATCH /api/projects/{slug}`.

## Phase 6 — Reporting (built)

Run → *Reports* (export centre), or `POST /api/projects/{slug}/runs/{id}/exports/{kind}`. Files land in the run's
`exports/` folder.

| Kind | File | Contents |
|---|---|---|
| `qa_report_pdf` | `qa_report.pdf` | Cover (branding, quality ring, KPIs), plain-language executive summary, result and severity charts, score breakdown, site profile, coverage heatmap, permissions, regression, bug list, one page per bug, appendices (results, traceability, method) |
| `bugs_pdf` / `bug_pdf` | `bug_report.pdf`, `bugs/BUG-001.pdf` | Bug-only report; single bug (also a *PDF* button on each bug) |
| `qa_xlsx` | `qa_report.xlsx` | Summary, Site Profile, Requirements, User Stories, Test Cases, Execution Results, Bugs, Permission Matrix, Traceability — frozen headers, filters, colour-coded, hyperlinks to screenshots / clips / videos |
| `jira_csv`, `trello_csv` | `bugs_jira.csv`, `bugs_trello.csv` | Importable bug lists (UTF-8 BOM, Jira wiki markup) |
| `traceability_csv` | `traceability.csv` | Requirement → story → test case → result → bug |
| `pytest_zip` | `pytest_suite.zip` (+ folder) | pytest + Selenium Page Object suite with README, `.env.example`, markers |
| `gherkin_zip`, `testcases_xlsx`, `requirements` | (Phase 3) | |

Privacy blur is applied to every embedded screenshot when on; credentials are never read by the exporters.
Branding (company, client, accent colour, logo) is set in *Settings → Report branding*.

**Verified (2026-10-05, DriveNow Rentals run):** all exports generated (PDF report 3 MB in 3 s). The exported pytest suite
ran against the demo app after a data reset: **49 passed, 9 failed, 2 skipped** — every failure is a real bug QA Pilot
had reported (accessibility violations, missing 10 % weekly discount, `/admin/revenue` open to agent and customer,
`/calendar` overflowing at 768 px); the 2 skips are tests that were not recorded.

## How to resume

```
Continue QA_PILOT_BUILD_PROMPT.md: finish the Phase 4 demo runs (resume), then Phase 5. Check git log and docs/PROGRESS.md for what's done.
```

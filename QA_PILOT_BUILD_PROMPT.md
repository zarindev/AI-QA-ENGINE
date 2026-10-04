# BUILD PROMPT — QA Pilot (AI Website QA Engine)

> Save this file in an empty project folder, open it in VS Code, and tell Claude Code:
> **"Read QA_PILOT_BUILD_PROMPT.md and execute it phase by phase."**
> In later sessions: **"Continue QA_PILOT_BUILD_PROMPT.md from Phase X. Check git log and docs/PROGRESS.md for what's done."**

---

## 0. Project variables (use these everywhere)

```
PROJECT_NAME   = QA Pilot
TAGLINE        = Give it a URL. It learns the app, writes the tests, runs them, and reports the bugs.
AUTHOR_NAME    = Muzahidul Rahman
AUTHOR_ROLE    = QA Automation Engineer & AI Automation Developer
GITHUB_URL     = https://github.com/YOUR_USERNAME/qa-pilot      (leave as placeholder)
UPWORK_URL     = https://www.upwork.com/freelancers/YOUR_PROFILE (leave as placeholder)
BRAND_PRIMARY  = #2563EB   (blue)
BRAND_PASS     = #16A34A   (green)
BRAND_FAIL     = #DC2626   (red)
BRAND_WARN     = #F59E0B   (amber)
BRAND_DARK     = #0A0F1C
FONT           = Inter (UI), JetBrains Mono (code, IDs, logs)
```

---

## 1. Mission

You are a senior QA architect, full-stack engineer and product designer. Build **QA Pilot**, a **fully local application** that runs on the user's own computer.

The user gives it the URL of any website or web application, from **any industry** (hospital management, car rental, e-commerce, school, HR, CRM, restaurant, real estate, banking, portfolio, blog…), plus optional login credentials for each user role. QA Pilot then:

1. **Explores** the site with Selenium, separately for every role.
2. **Detects** the domain, site type, roles, entities, features and workflows.
3. **Builds a Site Model** (knowledge graph) of how the app works.
4. **Infers requirements:** user stories, journeys, workflows, business rules.
5. **Designs test cases** with standard QA techniques; the user reviews and approves them.
6. **Executes** tests with an AI agent driving Selenium, capturing screenshots, video, console and network logs.
7. **Verifies** failures (re-runs, severity, confidence, de-duplication).
8. **Reports** professional bug reports and test documentation as PDF, Excel, CSV, Gherkin and an exportable pytest suite.

The core design principle: **no hardcoded templates per industry.** Every web app is made of roles, entities, operations, workflows and business rules. The engine discovers these generically; Claude's domain knowledge supplies industry common sense. Optional "Domain Packs" sharpen tests but are never required.

This repository will be **public on GitHub** and used as a **portfolio flagship and Upwork case study.** It must be easy for any stranger to clone and run, and it must ship with polished showcase assets (Section 12).

### Working rules
1. **Plan first.** Output the implementation plan and folder tree, then proceed without waiting unless genuinely blocked.
2. **Build phase by phase** (Section 10). After each phase: run tests, run the app, fix errors, update `docs/PROGRESS.md`, `git commit` (e.g. `feat(phase-2): site model and domain detection`).
3. **Never fake results.** No mocked AI or browser output in the real code path. Sample data only behind an explicit `--demo` flag.
4. **Test against real targets:** the three demo apps you build (Section 11) and these public automation-practice sites: `https://www.saucedemo.com`, `https://automationexercise.com`, `https://the-internet.herokuapp.com`, `https://opensource-demo.orangehrmlive.com`.
5. **Windows first, cross-platform always.** The author uses Windows + VS Code. Provide `.bat`, `.ps1`-safe and `.sh` scripts; use `pathlib`.
6. Anything you cannot verify gets a fallback, a logged warning and an entry in `docs/KNOWN_ISSUES.md`.
7. **Safety is non-negotiable** (Section 9).

---

## 2. Local-only architecture principles (hard requirements)

- **No database of any kind.** No SQLite, Postgres, Redis, MongoDB, or ORM. All state is stored as **plain files** (JSON, Markdown, images, MP4) in a local `workspace/` folder.
- **No cloud services, accounts or hosting.** Everything runs on `localhost`. The **only** external call is the Anthropic Claude API (the user's own key). Document this clearly in the README.
- **No Docker, no message queue, no background services** to install.
- **Minimum prerequisites for users who clone the repo:** Python 3.11+, Google Chrome, Git, an Anthropic API key. **Node.js must NOT be required** to run the app: commit the production build of the frontend into `backend/app/static/` so the Python server serves it directly. Node is only needed by developers who modify the UI.
- **Portable workspace:** a project folder can be zipped, moved to another machine and opened again. Paths stored inside JSON are always relative to the workspace.
- **Human-readable data:** every JSON file is pretty-printed with a `schema_version` field, so users can inspect or version-control results.

---

## 3. Tech stack (use exactly this)

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Browser automation | **Selenium 4** (Selenium Manager auto-installs the driver) + Chrome DevTools Protocol (`execute_cdp_cmd`) for console logs, network capture, screencast |
| AI brain | **Anthropic Claude API**: vision, tool use, strict JSON. Model configurable, default `claude-sonnet-5-5` |
| Backend | **FastAPI** + Uvicorn; **SSE** for live progress |
| Storage | **File-based repository layer**: Pydantic v2 models ↔ JSON files, atomic writes (temp file + `os.replace`), `filelock` for concurrent writes |
| Background jobs | In-process `ThreadPoolExecutor`; job state persisted in each run's `run.json` (runs interrupted by a restart are marked `interrupted` and resumable) |
| Search/filter | In-memory over loaded JSON (local scale; add a lightweight `index.json` per project for fast listing) |
| Graph logic | **NetworkX**; Site Model saved as JSON (node-link format) |
| Test data | **Faker** with domain-aware generators |
| Frontend | **React + TypeScript + Vite + Tailwind + shadcn/ui + lucide-react**, TanStack Query, **React Flow**, **Recharts**, Framer Motion |
| Video | CDP screencast frames → **ffmpeg** via `imageio-ffmpeg` (bundled binary, no manual install) → MP4 |
| Images | Pillow (annotation, privacy blur, thumbnails) |
| Accessibility | axe-core (`axe-selenium-python`) |
| Excel | **openpyxl** (styled multi-sheet workbooks) |
| PDF | Jinja2 HTML → Chrome `print_page` via Selenium (no WeasyPrint/GTK) |
| Exported automation | pytest + Selenium (Page Object Model) |
| Secrets | API key in `.env`; role credentials in `workspace/<project>/secrets.enc` encrypted with `cryptography` (Fernet), key in `.env` (auto-generated on first run) |
| Quality | pytest, Vitest, ruff, black, mypy (lenient), eslint, prettier; **GitHub Actions CI** for lint + tests |

**One-command run:** `start.bat` / `start.sh` launches the server at `http://localhost:8000` and opens the browser. Dev mode: Vite on `:5173` proxied to the API.

---

## 4. Folder structure

```
qa-pilot/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app, serves static UI
│   │   ├── static/                 # COMMITTED production build of frontend
│   │   ├── api/                    # projects, runs, sitemodel, requirements, testcases,
│   │   │                           # executions, bugs, reports, settings, events (SSE)
│   │   ├── core/                   # config, logging, paths, crypto, cost tracking
│   │   ├── storage/
│   │   │   ├── schemas.py          # Pydantic models (Section 5)
│   │   │   ├── repository.py       # load/save/list, atomic writes, locks
│   │   │   ├── index.py            # per-project index.json for fast listing
│   │   │   └── migrations.py       # schema_version upgrades for old JSON
│   │   ├── jobs/                   # executor.py, run_state.py
│   │   ├── browser/                # driver, dom_snapshot, auth, recorder, locators
│   │   ├── explore/                # crawler, checks
│   │   ├── understand/             # classifier, model_builder, domain_packs/*.yaml
│   │   ├── requirements/           # stories, rules
│   │   ├── testdesign/             # generator, testdata
│   │   ├── execute/                # agent, actions, replayer
│   │   ├── verify/                 # judge, confirm, severity, dedupe
│   │   ├── reports/                # pdf, excel, csv_jira, gherkin, pytest_export, templates/
│   │   └── ai/                     # client.py (retries, caching, budget), prompts/
│   ├── tests/                      # unit tests + HTML fixtures
│   └── cli.py                      # `python cli.py run <url> --mode safe`
├── frontend/src/                   # pages/, components/, lib/, hooks/
├── demo_targets/
│   ├── clinic_app/  car_rental_app/  shop_admin_app/
│   ├── manifests/                  # planted_bugs.json (engine must NEVER read)
│   └── start_demos.bat / start_demos.sh
├── workspace/                      # gitignored (keep .gitkeep): all user data
├── config/settings.yaml
├── docs/
│   ├── assets/                     # banner.svg, logo.svg, social-preview.png, screenshots/, demo.gif
│   ├── samples/                    # sample report PDF, Excel, bug report from demo runs
│   ├── case-study/                 # case-study.html, CASE_STUDY.md, UPWORK_LISTING.md, export/
│   ├── ARCHITECTURE.md, STORAGE.md, SITE_MODEL.md, TEST_TECHNIQUES.md
│   ├── PROGRESS.md, KNOWN_ISSUES.md, LEGAL.md, TROUBLESHOOTING.md
│   └── benchmarks.json
├── scripts/
│   ├── benchmark.py, capture_screenshots.py, export_case_study.py,
│   ├── build_frontend.bat/.sh      # rebuild UI into backend/app/static
│   └── seed_demo.py
├── .github/
│   ├── workflows/ci.yml
│   ├── ISSUE_TEMPLATE/ (bug_report.md, feature_request.md)
│   └── pull_request_template.md
├── setup.bat / setup.sh            # venv, pip install, .env creation, Chrome check
├── start.bat / start.sh
├── requirements.txt                # pinned versions
├── .env.example, .gitignore
├── README.md, LICENSE (MIT), CHANGELOG.md, CONTRIBUTING.md, SECURITY.md
```

---

## 5. Storage design (file-based)

```
workspace/
├── settings.json                       # UI settings (branding, budgets, viewports)
└── projects/
    └── <project-slug>/
        ├── project.json                # url, name, environment, authorization record
        ├── secrets.enc                 # encrypted role credentials / saved sessions
        ├── index.json                  # summary of runs for fast listing
        └── runs/
            └── <YYYYMMDD-HHMMSS>/
                ├── run.json            # mode, status, current stage, progress, token cost
                ├── crawl/pages.json    # pages + elements, per role
                ├── site_profile.json   # domain, sub-type, confidence, evidence
                ├── site_model.json     # NetworkX node-link graph
                ├── requirements.json   # stories, workflows, business rules + status
                ├── permissions.json    # role × page × action matrix
                ├── testcases.json      # cases with approval status
                ├── executions/<TC-ID>.json   # step results
                ├── bugs.json
                ├── artifacts/          # screenshots/, videos/, clips/, logs/
                ├── replay/             # recorded replay scripts per test case
                └── exports/            # generated PDF, XLSX, CSV, .feature, pytest suite
```

Rules: every write is atomic; every model has `schema_version`; the repository layer is the **only** code that touches files (the rest of the app depends on its interface, so storage could be swapped later); `docs/STORAGE.md` documents the layout.

### Core models (Pydantic)
- **Project**: url, name, environment (`production|staging|test`), authorized_by, authorized_at.
- **Role**: name, login strategy (`credentials|manual_session`), secret reference.
- **Run**: mode (`safe|full`), status, stage, progress, started/finished, token usage.
- **Page / Element**: url template, title, role visibility, status code, screenshot path; element type, label, locator set.
- **SiteProfile**: domain, sub_type, confidence, summary, evidence[].
- **Entity**: name, fields[{name, type, required, validation}], relations.
- **Feature / Workflow / BusinessRule / PermissionCell / UserStory** (as in Section 6).
- **TestCase**: id `TC-<MOD>-001`, title, module, technique, type, priority, preconditions, test_data, steps[], expected_result, links, status (`draft|approved|skipped`).
- **Execution / StepResult**: result (`pass|fail|blocked|error`), role, viewport, video, step-by-step evidence.
- **Bug**: id `BUG-001`, title, summary, severity, priority, confidence, environment, preconditions, steps_to_reproduce[], expected, actual, evidence[], reproducibility, links, status.

---

## 6. Engine specification (8 stages)

### ① Explore
- Inputs: URL, scope (same domain + include/exclude patterns), max pages, max depth, viewports.
- Breadth-first crawl: public pages first, then once per role.
- Login: (a) automatic, where the AI finds the login form and uses stored credentials; or (b) **manual session capture**, where a visible browser opens, the user logs in (handles 2FA), and cookies are saved encrypted. Never bypass CAPTCHA or 2FA.
- Per page: URL, title, status, screenshot, simplified DOM, forms, inputs (type, name, label, required, pattern, min/max), buttons, links, table headers, console errors, failed requests, load time.
- Normalize URLs into templates (`/patients/12` ≈ `/patients/13`); ignore tracking parameters.
- **Safe Mode:** never click elements whose text or context suggests delete, remove, cancel, pay, purchase, checkout, transfer, etc. (deny-list in `settings.yaml`). Only submit known non-destructive forms (search, filter).

### ② Understand (domain detection)
Claude receives page summaries and representative screenshots and returns strict JSON: `domain`, `sub_type`, `confidence`, `summary`, `roles[]`, `modules[]`, `features[]`, `entities[]` (with fields), `evidence[]`. Show the evidence in the UI.
Domain Packs (YAML) for healthcare, rental, ecommerce, education, hr, crm, restaurant, real_estate, banking, booking, portfolio, blog add typical features, critical rules and edge cases. The engine must fully work without a matching pack.

### ③ Site Model
Combine crawl + classification into a NetworkX graph (entities, fields, relations, pages, operations, workflows as state machines, roles, permissions). Save to `site_model.json`; serve in React Flow format.

### ④ Requirements
- **User stories** with acceptance criteria per role and feature.
- **Workflows** as ordered steps + state diagrams.
- **Business rules** with a testable formula or condition, source, confidence. Status starts `proposed`; the user confirms, edits or rejects them in the UI. Only confirmed rules drive business-rule tests.
- Export a **Reverse-Engineered Requirements Document** (PDF + Markdown).

### ⑤ Test design
Generate cases from the Site Model and label each with its technique:

| Technique | Generates |
|---|---|
| Smoke / navigation | Every page reachable per role, no errors |
| CRUD | Create, read, update, delete per entity |
| End-to-end workflow | Each workflow start to finish |
| Form validation | Required, formats, lengths |
| Boundary value | min, min−1, max, max+1, zero, empty |
| Equivalence partitioning | Valid / invalid classes per field |
| Negative | Invalid inputs, impossible sequences |
| State transition | Allowed and forbidden transitions |
| Role / permission | Each role × restricted page/action, incl. direct-URL access |
| Data integrity | Create in one module → verify everywhere it should appear |
| Business rule | Engine recalculates expected values |
| UI / responsive | Overflow and broken layout at 1440 / 768 / 390 |
| Accessibility | axe-core violations |

Priority P1 (core workflows, money, medical, permissions) → P4 (cosmetic). Domain-aware fake test data only, **never real personal data**. Review UI: approve, edit, skip, add (including plain English, e.g. "Test that a receptionist cannot delete a doctor"). Show estimated cost and time before execution.

### ⑥ Execute
- **Observe → decide → act** agent loop. Input per turn: test case, current step, screenshot, simplified DOM with **indexed interactive elements** (`[12] button "Save Patient"`), recent history.
- Tools: `click(index)`, `type(index, text, clear)`, `select(index, option)`, `check(index)`, `upload(index, file)`, `navigate(url)`, `scroll(direction)`, `wait_for(...)`, `read(index)`, `assert(condition, evidence)`, `finish(pass|fail|blocked, reason)`.
- Limits per test: max steps, tokens and time.
- Record every step (action, target, input, before/after screenshot, observation), full-test video, console and network logs.
- Save successful runs as **replay scripts** with multi-strategy locators (id, name, aria-label, text, relative position, CSS). Later runs replay deterministically and fall back to the agent only when a locator fails (self-healing).
- Safe Mode guard runs before **every** action.
- Created records use a `QAP_` prefix; optional cleanup at the end in Full Mode.

### ⑦ Verify
- Detection layers: (1) automatic checks (4xx/5xx, broken links/images, JS errors, failed requests, timeouts, error pages, overflow, axe, slow pages); (2) AI expected-vs-actual judgement with mandatory evidence; (3) business-rule recalculation in Python.
- Re-run failures (default 2×) → reproducibility `3/3`; `1/3` = flaky.
- Severity (Critical / Major / Minor / Trivial) and priority with written reasoning; money, medical and permission failures weigh higher.
- Confidence score per bug; low-confidence bugs go to a "Needs review" queue.
- De-duplicate by root symptom.
- Produce a trimmed **bug clip** (10–25 s, captions burned in) and an **annotated screenshot**.

### ⑧ Report
**Bug report fields:** Bug ID · Title · Summary · Module · Environment (browser + version, OS, viewport, URL, date/time, role) · Severity · Priority · Preconditions · Steps to Reproduce (numbered, with data) · Expected · Actual · Evidence (annotated screenshot, clip, console, network) · Reproducibility · Linked Test Case · Linked Requirement · Status.

**Exports** (saved to the run's `exports/` folder and downloadable from the UI):
- **Excel workbook:** `Summary`, `Site Profile`, `Requirements`, `User Stories`, `Test Cases`, `Execution Results`, `Bugs`, `Permission Matrix`, `Traceability` (styled, colour-coded, frozen headers, filters, hyperlinks to evidence).
- **PDF QA report:** cover, plain-language executive summary, quality score, charts, site profile, coverage heatmap, one page per bug, appendices.
- **Bug-only PDF** and **single-bug PDF**.
- **CSV** for Jira / Trello import.
- **Gherkin** `.feature` files.
- **pytest + Selenium suite** (Page Object Model) with its own README.
- **Traceability matrix:** Requirement → Story → Test Case → Result → Bug.

---

## 7. Standout features (must be included)

1. **Site Knowledge Graph viewer** (React Flow).
2. **Reverse-engineered requirements document** from just a URL.
3. **Role permission matrix** (expected vs observed, holes highlighted).
4. **Cross-module data integrity checks.**
5. **Live Run Viewer:** live screenshot stream, step narration, pass/fail ticker.
6. **One-click Bug Replay** in a visible browser.
7. **Coverage heatmap** (green / red / amber / grey).
8. **Quality Score 0–100** with sub-scores (Functional, Permissions, Data Integrity, UI, Accessibility, Performance); formula in `docs/ARCHITECTURE.md`.
9. **Regression comparison** between runs: fixed / new / reappeared / still open.
10. **Two-audience reports** (business summary + technical detail).
11. **Plain-English test authoring.**
12. **Multi-viewport runs.**

---

## 8. UI / UX

**Direction:** premium dark-first QA command centre (Linear × BrowserStack). `BRAND_DARK` background, blue primary, green/red/amber statuses, glass cards, 12–16px radius, subtle borders, micro-animations, skeleton loaders, meaningful empty states, toasts, `Ctrl+K` command palette, light-mode toggle. Desktop-first (≥1280px).

**First-run onboarding:** if no API key is set, show a friendly setup screen (paste key → validated → saved to `.env`), Chrome detection status, and a **"Try with a demo app"** button that starts a sample run against the clinic demo app.

**Screens:**
1. **Projects**: cards with quality score ring, domain badge, last run, open bugs.
2. **New Project wizard**: URL → environment type → authorization confirmation → roles and credentials (or manual login) → scope and limits → mode (Full only for staging/test, second confirmation).
3. **Run Overview**: 8-stage stepper with live progress.
4. **Site Profile**: domain + confidence + evidence, roles, modules, feature inventory.
5. **Site Model**: knowledge graph + site map.
6. **Requirements**: stories, workflow diagrams, business rules with Confirm / Edit / Reject.
7. **Test Cases**: grouped table, filters, side-panel editor, bulk approve, plain-English add, cost estimate, "Run approved tests".
8. **Live Run Viewer.**
9. **Results**: summary + per-test drill-down with step screenshots and video.
10. **Bugs**: severity board + table; detail page with all fields, annotated screenshot, clip, logs, Replay, status, "Needs review" queue.
11. **Permission Matrix.**
12. **Coverage & Quality**: heatmap, score breakdown, regression comparison.
13. **Reports**: export centre, branded via Settings.
14. **Settings**: API key status, model, token budget, browser options, Safe Mode deny-list, branding, workspace folder location (with "Open folder" button), danger zone.

---

## 9. Safety, ethics, privacy (enforce in code)

- Every project requires an **"I own this website or am authorized to test it"** confirmation, timestamped in `project.json`.
- **Safe Mode by default.** Full Mode only for environments marked `staging`/`test`, behind a second confirmation.
- No CAPTCHA solving, 2FA bypass, brute force or exploitation. Permission tests use only provided credentials and crawl-discovered URLs.
- Polite rate limiting (configurable).
- Credentials encrypted; never written to logs, reports or exports.
- **Privacy blur** of emails, phone numbers and names in screenshots/video before export (default on for healthcare and banking).
- `workspace/` and `.env` are gitignored; a pre-commit check warns if secrets are staged.
- `docs/LEGAL.md` and `SECURITY.md` explain all of this.

---

## 10. Build phases

| Phase | Build | Done when |
|---|---|---|
| **1. Foundation + Explore** | Scaffold, config, **file storage layer** with tests, Claude client, driver, DOM snapshot, crawler (public + per role + manual session), automatic checks, CLI, basic HTML report | `cli.py run https://www.saucedemo.com` crawls, logs in, writes the workspace files and reports findings |
| **2. Understand + Site Model** | Classifier, Domain Packs, model builder, FastAPI + React shell, SSE, job executor, onboarding screen, Site Profile + Site Model screens, `setup`/`start` scripts, static UI build committed | All 3 demo apps classified correctly |
| **3. Requirements + Test Design** | Stories, workflows, rules with confirm flow, test generator, test data, review UI, requirements PDF, Excel test cases, Gherkin | Approved suites exist for all 3 demo apps |
| **4. Execute + Verify** | Agent, actions, recorder, replayer, self-healing, judge, re-runs, severity, dedupe, clips, annotated screenshots, Live Run Viewer, Results + Bugs screens | Bugs found on demo apps with full evidence |
| **5. Advanced checks** | Permission matrix, data integrity, business rules, multi-viewport, accessibility, quality score, heatmap, regression, Bug Replay, privacy blur | All Section 7 features work |
| **6. Reporting** | All exports in Section 6 ⑧ | Exports open in Excel / PDF viewer; exported pytest suite runs against a demo app |
| **7. Public repo polish** | README, CONTRIBUTING, SECURITY, TROUBLESHOOTING, CI workflow + badge, issue templates, `.env.example`, fresh-clone test | Section 13 "fresh clone" check passes |
| **8. Showcase package** | Benchmarks, screenshots, sample reports, case study slides, PDF, Upwork images, listing text (Section 12) | All files in Section 12 exist and look polished |

---

## 11. Demo targets with planted bugs (the proof)

Build three small, realistic apps in `demo_targets/` (Flask or FastAPI + Jinja + clean CSS). **To stay consistent with the no-database rule, each demo app stores its data in a JSON file** and includes a "Reset demo data" route. Each runs on its own port with seeded fake data and multiple roles:

- **Clinic management** (`:8101`): Admin, Doctor, Receptionist. Patients, doctors, appointments, prescriptions, billing, reports.
- **Car rental** (`:8102`): Admin, Agent, Customer. Cars, availability calendar, bookings, pickup/return, invoices, revenue report.
- **Shop admin** (`:8103`): Admin, Cashier. Products, prices, stock, sales, purchases, profit report.

`start_demos.bat` / `.sh` launches all three. Demo credentials are listed in the README.

Plant **12–15 bugs per app** across categories: calculation/business rule, permission, validation, data integrity, state transition, broken link, JS error, UI/responsive, accessibility. Examples: doctor double-booking allowed; invoice ignores insurance; return date before pickup accepted; cashier opens the profit report via direct URL; stock goes negative; deleted product still selectable in sales.

`manifests/planted_bugs.json` per app (id, category, description, location, expected severity). **The engine must never read the manifests.** Only `scripts/benchmark.py` uses them: it runs QA Pilot on each app (Full Mode, test environment), matches reported bugs to planted bugs (Claude-assisted matching, then a printed table for the author to confirm), and writes `docs/benchmarks.json`: detection rate per app and category, false positives, domain detection accuracy, test cases generated, run time, token cost. **These real numbers are the only numbers used anywhere in the README, case study and Upwork assets.**

---

## 12. Showcase package (portfolio + Upwork + GitHub)

### 12.1 Screenshots of the app
`scripts/capture_screenshots.py` starts QA Pilot, loads a completed demo run, and uses Selenium to capture every major screen at **1440×900 with 2× device scale** into `docs/assets/screenshots/` (dark mode, plus light mode for the 3 key screens). Use only demo apps, never third-party sites.

### 12.2 Sample outputs
Copy a real demo run's Excel workbook, full PDF report and one single-bug PDF into `docs/samples/`, with privacy blur on.

### 12.3 Case study slides — `docs/case-study/case-study.html`
Single self-contained HTML file (inline CSS, Inter, no external JS), premium dark style in brand colours. Each section is one slide, exactly **1600×1200 (4:3)**, using real screenshots in browser-window mockups:

1. **Cover**: name, tagline, hero screenshot, tags (AI · QA Automation · Selenium · Python), author.
2. **The Challenge**: manual QA is slow and costly, small teams ship untested apps, vague bug reports. 3 pain cards.
3. **The Solution**: one sentence + 8-stage strip.
4. **Works on Any Industry**: 3 demo domains with what was detected in each.
5. **Inside the Engine**: knowledge graph screenshot + explanation.
6. **Test Design**: technique list + test case screenshot.
7. **Live Execution**: Live Run Viewer screenshot.
8. **Bug Reports Developers Love**: annotated bug detail screenshot with fields called out.
9. **Engineering Highlights**: agent loop, self-healing replay, re-run verification, permission matrix, data integrity, privacy blur, 100% local file-based architecture, exportable pytest suite.
10. **Results**: big-number stats from **real** `docs/benchmarks.json` only.
11. **Tech Stack**: badge grid.
12. **Call to Action**: "Want automated QA for your web app?" + AUTHOR_NAME + Upwork link.

### 12.4 Export — `scripts/export_case_study.py`
Uses headless Chrome to produce, in `docs/case-study/export/`:

```
export/
├── QA-Pilot-Case-Study.pdf          # all 12 slides, one per page, 4:3, fonts embedded
├── slides/slide-01.png … slide-12.png   # 1600×1200 PNG
├── upwork/
│   ├── 00-thumbnail.png             # 1600×1200, Upwork cover / thumbnail
│   ├── 01-…png … 06-…png            # 6 gallery images (1600×1200) chosen for Upwork:
│   │                                #   solution, any-industry, knowledge graph,
│   │                                #   live run, bug report, results
│   └── jpg/                         # same images as optimized JPG (<2 MB each, quality 90)
├── social/
│   ├── github-social-preview.png    # 1280×640 for repo Settings → Social preview
│   └── linkedin-x-post.png          # 1200×675
```

**Upwork thumbnail design:** must read clearly at small size. Big project name, one short benefit line, one striking screenshot, a bold stat badge from real benchmarks (e.g. "Found X of Y planted bugs"), high contrast, no small text. Keep important content inside a centred safe area (inner 90%) so cropping in Upwork's grid doesn't cut it.

Verify after export: check each PNG's exact dimensions, file size and that no text overflows (render-check with Selenium screenshots).

### 12.5 Upwork listing — `docs/case-study/UPWORK_LISTING.md`
Ready to paste, using only real numbers:
- **Project title** (≤70 characters)
- **Your role** (one line)
- **Project description** (≤600 characters)
- **Skills** (5 tags)
- **Image upload order** (which files from `export/upwork/` to upload, in order) + the PDF to attach
- **Project URL** = GITHUB_URL placeholder

### 12.6 `docs/case-study/CASE_STUDY.md`
The full case study in clean markdown (Challenge → Solution → Process → Features → Engineering → Results → Tech → CTA), embedding the slide PNGs.

### 12.7 README.md (public repository, must be beautiful and easy to follow)
Optimized for someone who has never seen the project and wants it running in 5 minutes:

1. **Hero:** centred `docs/assets/banner.svg` (create: 1280×400, dark gradient, blue glow, logo mark, name, tagline). Centred shields.io badges: CI status, Python, Selenium, Claude AI, FastAPI, React, License MIT, "100% Local".
2. One-paragraph pitch + centred `docs/assets/demo.gif` (HTML comment explaining how the author should record it).
3. **Table of contents.**
4. **✨ Highlights**: 3-column HTML table of benefit cards.
5. **🔒 100% local**: short callout: no database, no cloud, no accounts; data lives in `workspace/` as readable files; only the Claude API is called.
6. **🚀 Quick start** (the most important section, copy-paste ready):
   - Prerequisites table: Python 3.11+, Google Chrome, Git, Anthropic API key (with a link to get one). State that Node.js is **not** needed.
   - Windows block: `git clone …` → `cd qa-pilot` → `setup.bat` → `start.bat`
   - macOS / Linux block: same with `.sh`.
   - "Your first test in 2 minutes": `start_demos.bat` → open `http://localhost:8000` → New Project → `http://localhost:8101` → use the listed demo credentials.
   - CLI usage examples.
7. **🧭 How it works**: 8-stage strip + Mermaid architecture flowchart.
8. **🌍 Works on any industry**: table of the 3 demo domains.
9. **📸 Screenshots**: HTML table grid with captions.
10. **📄 Sample outputs**: links to `docs/samples/` + an inline rendered example bug report.
11. **🧪 Test techniques** table.
12. **📊 Benchmarks** from `docs/benchmarks.json`.
13. **📁 Where your data lives**: collapsible `workspace/` tree.
14. **⚙️ Configuration**: `.env` and `settings.yaml` tables in `<details>`.
15. **🛡️ Safety & responsible use**: Safe Mode, authorization, privacy blur, link to LEGAL.md.
16. **🛠️ Tech stack** table.
17. **❓ Troubleshooting / FAQ**: Chrome not found, API key errors, port in use, PowerShell execution policy, antivirus blocking the driver, link to TROUBLESHOOTING.md.
18. **🗺️ Roadmap** (checkboxes), **🤝 Contributing** (link), **📜 License**.
19. **Author card**: centred AUTHOR_NAME and AUTHOR_ROLE, "Need QA automation or a custom testing tool for your app? Let's talk.", Upwork + GitHub `for-the-badge` buttons.

Rules: every section skimmable in 5 seconds; every image path exists; Mermaid validated; all commands tested in a fresh clone.

---

## 13. Final quality checklist

- [ ] **Fresh-clone test:** clone the repo into a new folder, run `setup.bat` → `start.bat` with only Python + Chrome installed (no Node). The app opens, onboarding works, the demo run completes. Repeat with `.sh`.
- [ ] No database or server dependency anywhere (`requirements.txt` contains no DB drivers/ORMs).
- [ ] Deleting `workspace/` resets the app cleanly; zipping a project folder and opening it elsewhere works.
- [ ] Interrupted runs are marked and resumable after restart.
- [ ] Safe Mode guard verified by tests; credentials never appear in logs, JSON or exports.
- [ ] All 3 demo apps classified correctly; real benchmarks in `docs/benchmarks.json`.
- [ ] Every bug has all fields, annotated screenshot, clip and reproducibility.
- [ ] Excel, PDFs, CSV, Gherkin and pytest exports work; pytest suite runs against a demo app.
- [ ] Every screen has loading, empty and error states.
- [ ] CI passes (lint + unit tests run offline).
- [ ] README renders correctly on GitHub; all images exist; all commands verified.
- [ ] Showcase files exist with exact sizes: 12 slides + PDF, Upwork thumbnail + 6 gallery images (PNG + JPG), GitHub social preview, LinkedIn/X image, UPWORK_LISTING.md, CASE_STUDY.md, sample reports.
- [ ] Docs written: ARCHITECTURE, STORAGE, SITE_MODEL, TEST_TECHNIQUES, LEGAL, SECURITY, TROUBLESHOOTING, CONTRIBUTING, KNOWN_ISSUES, CHANGELOG.
- [ ] Final summary to the author: what was built, how to run it, real benchmark results, known limitations, and manual to-dos (record demo GIF, set the GitHub social preview image, replace URL placeholders).

**Start now with the plan and Phase 1.**

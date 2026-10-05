# Changelog

All notable changes to QA Pilot. The format follows [Keep a Changelog](https://keepachangelog.com/).

## [0.1.0] — 2026-10-05

First public version.

### Engine (8 stages)
- **Explore** — Selenium 4 crawler (public + every role, manual login for 2FA/SSO), network-aware readiness,
  automatic checks (HTTP errors, broken links and images, JS errors, failed requests, error text, mixed content,
  slow pages, horizontal overflow).
- **Understand** — Claude classifier with an offline heuristic fallback and 12 domain packs.
- **Site model** — NetworkX knowledge graph of pages, roles, entities and flows; React Flow viewer.
- **Requirements** — reverse-engineered user stories, workflows with state machines and business rules
  (proposed → confirmed by a person); requirements PDF and Markdown.
- **Test design** — rules-based + Claude test cases (13 techniques), Faker test data, cost estimate, review UI,
  plain-English test authoring, Excel and Gherkin export.
- **Execute** — AI browser agent (one action per turn, Safe Mode guard on every action), rule runner (smoke,
  permission, responsive, axe-core accessibility), step screenshots, captioned videos, replay scripts with
  self-healing, resumable runs, cost and token budgets, multi-viewport runs.
- **Verify** — re-runs for reproducibility, flaky → Needs review, Claude-written bug reports, de-duplication,
  annotated screenshots and bug clips, Python recalculation of business rules.
- **Report** — Quality Score, coverage heatmap, permission matrix, regression comparison; PDF QA report (business
  summary + technical detail), bug-only and single-bug PDFs, full Excel workbook, Jira / Trello CSV, traceability
  matrix, pytest + Selenium Page Object suite.

### App
- FastAPI + SSE backend, React UI built into the package (no Node.js needed), command palette, light/dark theme.
- File-based workspace (atomic writes, locks, schema versions, migrations) — no database.
- Encrypted credentials, privacy blur, authorization record, Safe / Full Mode, secret-check git hook.
- Three demo apps with 45 planted bugs and answer keys for benchmarking.
- CLI: `run`, `review`, `execute`, `export`, `projects`, `runs`, `report`.

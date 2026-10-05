# Contributing to QA Pilot

Thanks for helping! Bug reports, domain packs, docs and code are all welcome.

## Development setup

```bash
git clone https://github.com/YOUR_USERNAME/qa-pilot && cd qa-pilot
./setup.sh                         # Windows: setup.bat — also enables the secret-check git hook
.venv/bin/pip install -r requirements-dev.txt
./demo_targets/start_demos.sh      # three local apps with planted bugs (ports 8101–8103)
./start.sh --port 8000             # backend + built UI
```

UI development (only if you change `frontend/`):

```bash
cd frontend && npm install && npm run dev      # Vite on :5173, proxies /api to :8000
scripts/build_frontend.sh                      # rebuild backend/app/static — commit the result
```

Users never need Node.js, so the production build in `backend/app/static` **must be committed** with UI changes.

## Before you open a pull request

```bash
.venv/bin/ruff check backend scripts demo_targets
.venv/bin/black --check backend scripts
.venv/bin/mypy backend/app
.venv/bin/pytest backend/tests -q            # offline: no API key needed, Chrome tests skip without Chrome
cd frontend && npx tsc -b && npx eslint src && npx vitest run
```

CI runs the same checks plus `python scripts/check_secrets.py --all`.

## Ground rules

- **Local-only.** No database, no hosted services, no telemetry. The only external call is the Anthropic API.
  Storage goes through `backend/app/storage/repository.py` (atomic writes, file locks, `schema_version`).
  A schema change needs a migration in `storage/migrations.py`.
- **Never fake results.** Numbers in docs and the README come from real runs (`scripts/benchmark.py`).
- **Safety first.** Every browser action passes `SafetyGuard`. Changes to Safe Mode need tests in
  `backend/tests/test_safety.py`. Credentials never reach logs, JSON documents or exports.
- **Claude calls** go through `backend/app/ai/client.py` (budget, caching, retries, usage accounting). Prompts live in
  `backend/app/ai/prompts/*.md`. Unit tests must not call the API — pass a fake client.
- **Demo apps** (`demo_targets/`) contain deliberate bugs marked `# PLANTED XX-nn`; the answer keys in
  `demo_targets/manifests/` are read only by `scripts/benchmark.py`, never by the engine. The demo apps are kept
  compact on purpose and are excluded from Black.
- Keep functions small and names plain; match the style of the surrounding code.

## Adding a domain pack

Copy a file in `backend/app/understand/domain_packs/`, adjust keywords, typical entities, roles, workflows and
business-rule hints, and add a classification test in `backend/tests/test_understand.py`.

## Commit messages

`feat(scope): …`, `fix(scope): …`, `docs: …`, `test: …`, `chore: …`.

## What and why

## How it was tested
- [ ] `pytest backend/tests` passes (offline, no API key)
- [ ] `ruff check backend` / `black --check backend` / `mypy backend/app`
- [ ] UI changed → `scripts/build_frontend.sh` run and `backend/app/static` committed
- [ ] Docs updated (README / docs/*) if behaviour changed

## Safety
- [ ] No secrets, `.env`, `workspace/` data or customer screenshots in this PR
- [ ] Safe Mode behaviour unchanged, or the change is covered by tests

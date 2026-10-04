# QA Pilot

> Give it a URL. It learns the app, writes the tests, runs them, and reports the bugs.

**Status: under construction (Phase 1 of 8 complete).** The full README arrives in Phase 7 — see
[docs/PROGRESS.md](docs/PROGRESS.md).

100% local: no database, no cloud, no accounts. Data lives in `workspace/` as readable files; the only external
call is the Anthropic Claude API with your own key.

## Try the Phase 1 explorer

Requires Python 3.11+ and Google Chrome.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt          # Windows: .venv\Scripts\pip install -r requirements.txt
cd backend
../.venv/bin/python cli.py run https://www.saucedemo.com \
    --role standard:standard_user:secret_sauce --i-am-authorized --open
```

It explores the public pages and every role you pass, runs automatic checks (HTTP errors, JS errors, failed
requests, broken images/links, slow pages, overflow, error text) and writes an HTML report. Safe Mode is the
default: nothing that looks like delete, pay, checkout, transfer… is ever clicked.

Only test sites you own or are authorized to test.

## License

MIT © Muzahidul Rahman

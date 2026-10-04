# QA Pilot

> Give it a URL. It learns the app, writes the tests, runs them, and reports the bugs.

**Status: under construction (Phase 2 of 8 complete).** The full README arrives in Phase 7 — see
[docs/PROGRESS.md](docs/PROGRESS.md).

100% local: no database, no cloud, no accounts. Data lives in `workspace/` as readable files; the only external
call is the Anthropic Claude API with your own key.

## Try it

Requires Python 3.11+ and Google Chrome (Node.js is **not** needed).

| | Windows | macOS / Linux |
|---|---|---|
| Install | `setup.bat` | `./setup.sh` |
| Start | `start.bat` | `./start.sh` |
| Demo apps | `demo_targets\start_demos.bat` | `./demo_targets/start_demos.sh` |

QA Pilot opens at http://localhost:8000 (or the next free port). Click **Try with a demo app**, or create a project
for `http://localhost:8101` with the demo accounts listed in [demo_targets/README.md](demo_targets/README.md).

Command line:

```bash
cd backend
../.venv/bin/python cli.py run http://localhost:8101 --env test \
    --role "admin:admin@carepoint.test:Admin#2026" --i-am-authorized --open
```

Only test sites you own or are authorized to test.

## License

MIT © Muzahidul Rahman

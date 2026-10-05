# Troubleshooting

Logs: `workspace/logs/qa-pilot.log` (secrets are redacted). Each run also keeps
`workspace/projects/<slug>/runs/<run>/artifacts/logs/events.jsonl`.

## Setup

**“Python 3.11 or newer is required”**
Install Python from [python.org](https://www.python.org/downloads/). On Windows tick **“Add python.exe to PATH”**,
then open a *new* terminal and run `setup.bat` again. Check with `py -3 --version` or `python --version`.

**PowerShell: “running scripts is disabled on this system”**
Run the `.bat` files from *Command Prompt*, or double-click them in Explorer. If you prefer PowerShell, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once. (`setup.bat` / `start.bat` are batch files and are not
affected by the PowerShell policy when started from `cmd`.)

**`pip install` fails behind a proxy**
Set `HTTPS_PROXY=http://proxy:port` before running setup, or install with
`.venv\Scripts\python -m pip install -r requirements.txt --proxy http://proxy:port`.

**Node.js / npm errors**
You do not need Node.js. The UI is already built into `backend/app/static`. Only contributors who change the UI
run `scripts/build_frontend.*`. If `npm install` crashes with *“Cannot read properties of null (reading 'edgesOut')”*,
`frontend/.npmrc` already sets `legacy-peer-deps=true` — update npm (`npm i -g npm`) and retry.

## Chrome

**“Google Chrome: NOT FOUND”**
Install Google Chrome from [google.com/chrome](https://www.google.com/chrome/). Selenium Manager downloads the
matching driver automatically on the first run (it needs internet access once).

**Antivirus blocks `chromedriver`**
Some antivirus tools quarantine the driver that Selenium Manager downloads into `~/.cache/selenium`
(Windows: `%USERPROFILE%\.cache\selenium`). Allow that folder, or download the
[matching chromedriver](https://googlechromelabs.github.io/chrome-for-testing/) yourself and set
`SE_CHROMEDRIVER=C:\path\to\chromedriver.exe`.

**Chrome opens and closes immediately / “session not created”**
Chrome updated while QA Pilot was running. Close all QA Pilot Chrome windows and start the run again; the driver
is matched to the new version automatically.

## Starting the app

**Port 8000 is already in use**
`start.bat` / `start.sh` pick the next free port (8001, 8002…) and print the address. To choose one yourself:
`start.bat --port 8100`. QA Pilot never stops other programs that use a port.

**The page shows “Internal Server Error” or stays blank**
Check the terminal where `start` runs and `workspace/logs/qa-pilot.log`. Make sure you opened the address that
`start` printed (it may not be 8000). A hard refresh (Ctrl+Shift+R) helps after an update.

## Claude API

**“The API key was rejected” / 401**
Paste the key again in *Settings* (or `.env` → `ANTHROPIC_API_KEY`). Keys start with `sk-ant-`. Create one at
[console.anthropic.com](https://console.anthropic.com/settings/keys).

**“must include the anthropic-workspace-id header”**
Your key is a user-level key (`sk-ant-usr-…`) that is not tied to a workspace. Enter the workspace ID on the
onboarding screen (Console → Settings → Workspaces), or set `ANTHROPIC_WORKSPACE_ID` in `.env`.

**“Your credit balance is too low”**
Add credits in the Anthropic Console (Billing). The run stops cleanly; press *Resume* — finished tests are kept.

**A run stopped with “budget reached”**
Each run has a cost limit (`ai.run_cost_budget_usd`, Settings → Claude). Raise it and resume.

**Rate limits (429)**
The client retries with back-off. Lower `execute.workers` in `config/settings.yaml` to run fewer tests in parallel.

## Exploring and testing

**Login fails for a role**
Check the credentials and the login URL (project → Roles). For CAPTCHA, 2FA or SSO use **Capture login**
(project page) or `cli.py run … --manual-login ROLE`: you sign in yourself in a visible browser and the session is
saved encrypted.

**Many tests are “blocked”**
They create or change data and the run is in Safe Mode. Use Full Mode on a staging/test environment, or skip them.

**The site is slow / pages time out**
Raise `browser.page_load_timeout_s` and lower `crawl.max_pages`. Very slow free hosting can take 15–30 s per page.

**A bug looks wrong**
Mark it *Not a bug* (it stops counting in the Quality Score) and open the test’s attempts in *Results* to see what
the agent did, step by step, with screenshots and video. Flaky and low-confidence bugs are in *Needs review*.

**Exported pytest suite fails on data that changed**
Recorded tests replay fixed data (e.g. a specific booking). Reset the test data, or run `pytest -m "not full_mode"`.

## Resetting

- Delete `workspace/` to start from scratch (keep `.env` to keep the API key and the credential encryption key).
- Settings → Danger zone → *Reset settings to defaults* forgets changes made in the Settings page.
- Demo apps: `python demo_targets/<app>/app.py --reset`, or `python scripts/seed_demo.py`.

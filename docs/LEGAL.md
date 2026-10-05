# Responsible use

QA Pilot drives a real browser through a website, submits forms and — in Full Mode — creates, changes and deletes
data. Use it only where you are allowed to.

## You must be authorized

- Test only websites **you own** or that you have **written permission** to test (for example a client contract
  or a statement of work that names the site and the environment).
- Every project records an *“I own this website or am authorized to test it”* confirmation with your name and a
  timestamp in `workspace/projects/<slug>/project.json`. Projects cannot be created without it — in the UI or the CLI.
- Testing third-party sites without permission can break their terms of service and computer-misuse laws
  (e.g. the US CFAA, the UK Computer Misuse Act). You are responsible for how you use this tool.

## What QA Pilot will not do

- No CAPTCHA solving, no 2FA or SSO bypass — use **manual login** (you sign in yourself in a visible browser).
- No brute force, credential stuffing, fuzzing for exploits, injection payloads or denial of service.
- Permission tests only use the credentials you provide and URLs the crawler discovered.
- Requests are rate-limited (`crawl.rate_limit_s`, default 0.5 s between pages per browser).

## Safe Mode and Full Mode

| | Safe Mode (default) | Full Mode |
|---|---|---|
| Allowed environments | production, staging, test | **staging and test only** |
| Clicks on delete / remove / pay / submit-order / logout… | blocked (deny-list, configurable) | allowed, except the always-blocked list |
| Form submissions that create or change data | blocked → tests reported as *blocked* | allowed, with fake `QAP_` data |
| Confirmation | one checkbox (authorization) | authorization **and** a second explicit confirmation |

Some actions are never performed in any mode (`safety.always_blocked`, e.g. “delete account”, “wipe all”,
“reset demo data”, “transfer funds”).

## Data and privacy

- Everything stays on your computer in `workspace/`. The only external service is the Anthropic Claude API, which
  receives page text, element lists and screenshots of the pages being tested. Do not test pages whose content you
  may not share with Anthropic under your agreements; see Anthropic’s commercial terms and data-usage policy.
- Credentials are encrypted (Fernet, key in `.env`) in `workspace/projects/<slug>/secrets.enc` and are never
  written to logs, JSON files, reports or exports. Known secrets are redacted from logs automatically.
- **Privacy blur** hides emails, phone numbers and people’s names in screenshots, clips and exports. It is on by
  default for healthcare and banking sites and can be switched on for any project.
- Delete a project (UI → project → Delete) to remove all of its data, including screenshots and videos.

## No warranty

QA Pilot is provided “as is” under the MIT License. AI-generated requirements, test cases and bug reports can be
wrong; bugs are re-run to measure reproducibility and low-confidence results are marked *Needs review*, but a
person should review findings before acting on them.

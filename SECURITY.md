# Security

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Use GitHub’s *Report a vulnerability* (Security →
Advisories) on this repository, or contact the maintainer through the profile linked in the README. Include steps to
reproduce and the version (`git rev-parse --short HEAD`). You will get an answer within a few days.

## How QA Pilot protects your data

| Topic | What happens |
|---|---|
| Where data lives | Only on your computer, in `workspace/` (or `QAP_WORKSPACE`). No database, no cloud, no telemetry. |
| Network | The local server listens on `127.0.0.1` only. The only outbound calls are the websites you test and the Anthropic API. |
| API key | Stored in `.env` (git-ignored). The UI only ever shows a masked hint. |
| Role credentials | Encrypted with Fernet in `workspace/projects/<slug>/secrets.enc`; the key (`QAP_SECRET_KEY`) is in `.env`. Project files store only a reference. |
| Logs | Known secrets are registered and redacted before anything is written. |
| Reports and exports | Built only from run documents — exporters never read `secrets.enc`. The pytest export reads credentials from environment variables at run time. |
| Screenshots | Privacy blur (emails, phones, names) for exports and bug evidence; on by default for healthcare and banking. |
| Commits | `setup` enables a git pre-commit hook (`scripts/check_secrets.py`) that blocks API keys, private keys, `.env`, `*.enc` and `workspace/` data. CI runs the same check on every push. |

## Things to keep in mind

- Anyone with access to your computer account can read `.env` and therefore decrypt `secrets.enc`. Use test
  accounts with the least privileges needed, not personal or production admin accounts.
- Page content and screenshots of the site under test are sent to Anthropic for the AI stages.
- Full Mode creates and deletes data. Use it on staging or test environments only (enforced).

## Supported versions

Only the latest `main` receives fixes.

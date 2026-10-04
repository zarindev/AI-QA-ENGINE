# Known issues and limitations

Things QA Pilot cannot verify or does not handle yet, each with the current fallback.

| Area | Limitation | Fallback / behaviour |
|---|---|---|
| DOM snapshot | Elements inside iframes and closed shadow roots are not indexed. | Pages still get screenshots and checks; AI stages see only the top document. |
| Login | CAPTCHA, 2FA and SSO are never bypassed (by design). | Use `--manual-login ROLE`: log in yourself in a visible browser; the session is saved encrypted. |
| Login | Re-authentication prompts inside a logged-in session (e.g. OrangeHRM's Maintenance module) look like a login page. | The crawler re-logs in up to 3 times per role, then skips that page. |
| Click discovery | Only link-like elements without a real `href` are clicked (anchors with `#`/`javascript:`, `role=link/menuitem/tab`), and never inside forms. | Buttons that navigate (e.g. "Add patient") are explored by the test agent in Phase 4. |
| Status codes | Status comes from the last *Document* response (CDP). Single-page apps that serve a 404 then redirect (e.g. GitHub Pages fallback) report the final 200. | The 404 hop is kept in `failed_requests` for inspection. |
| Slow hosts | Free-tier demo hosts (Heroku, OrangeHRM demo) sometimes take 15–30 s per page. | Eager page loading + bounded readiness wait; failed pages are retried once after recovery and listed in `crawl/pages.json → errors`. |
| Visible error text | Pattern-based (`Traceback`, `SQLSTATE`, `NaN`, `[object Object]`, …) and can false-positive on pages that *discuss* errors (e.g. a programming blog). | Severity is minor/major only; AI verification in Phase 4 confirms before anything becomes a bug. |
| Redaction | Secrets shorter than 4 characters are not redacted from logs/page text. | Use realistic passwords for test roles. |
| AI | Claude code paths need `ANTHROPIC_API_KEY`; without it, exploration runs on heuristics only. | The CLI says so up front. |
| Server-side fallbacks | `fallbacks: "default"` may be rejected for some accounts/models. | The client retries once without it, logs a warning and keeps fallbacks off for the run. |
| Understand (heuristic) | Entity extraction is noisy on large generic apps (OrangeHRM yields names like "Username", "Empnumber") and finds nothing on stores whose products are cards rather than tables/forms (saucedemo). Domain detection was correct on 7/7 crawled sites. | Confidence capped at 0.75; returns `other` when fewer than 4 distinct domain keywords are found. |
| Server port | Port 8000 may already be used by another app. | `start.bat` / `start.sh` pick the next free port (8001, 8002…) and print it. |
| Frontend install | npm 10 can crash with "Cannot read properties of null (reading 'edgesOut')" while resolving peer dependencies. | `frontend/.npmrc` sets `legacy-peer-deps=true`. Only UI developers need Node.js. |
| Manual login via UI | The "Capture login" window opens on the machine running QA Pilot (fine for a local app). | Waits up to 15 minutes for "I'm logged in". |
| API keys | User-level keys (`sk-ant-usr-…`) are not tied to a workspace; Anthropic rejects them without a workspace ID. An account without credits passes the key check (listing models is free) but fails on the first real request. | Set `ANTHROPIC_WORKSPACE_ID` (the onboarding screen asks for it), and QA Pilot reports an empty balance in plain words. |
| Permission tests | Rules-based permission cases assume a role should NOT open a screen it never reached from its own menus. A role may legitimately reach a screen the crawl didn't visit (page budget). | They are drafts: review them, skip false assumptions. Claude's permission rules come with a confidence. |
| Test design variance | Claude's part of the suite differs a little between regenerations (e.g. 62 → 60 cases). | Approved, edited and hand-written cases are always kept. |
| Estimates | The execution cost estimate assumes ~4.5k input tokens per agent step and 30 % re-runs; real cost depends on page size. | Shown as "≈"; Phase 4 records real usage per test. |

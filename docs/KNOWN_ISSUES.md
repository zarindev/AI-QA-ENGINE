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
| Understand (AI) | **The Claude classifier has not yet run against the real API** — no key was available while building Phase 2. The request shape, schema and error handling are unit-tested; the prompt itself is untested. | Without a key the heuristic classifier runs and is labelled as such. Verify with a key before Phase 3 relies on AI profiles. |
| Understand (heuristic) | Entity extraction is noisy on large generic apps (OrangeHRM yields names like "Username", "Empnumber") and finds nothing on stores whose products are cards rather than tables/forms (saucedemo). Domain detection was correct on 7/7 crawled sites. | Confidence capped at 0.75; returns `other` when fewer than 4 distinct domain keywords are found. |
| Server port | Port 8000 may already be used by another app. | `start.bat` / `start.sh` pick the next free port (8001, 8002…) and print it. |
| Frontend install | npm 10 can crash with "Cannot read properties of null (reading 'edgesOut')" while resolving peer dependencies. | `frontend/.npmrc` sets `legacy-peer-deps=true`. Only UI developers need Node.js. |
| Manual login via UI | The "Capture login" window opens on the machine running QA Pilot (fine for a local app). | Waits up to 15 minutes for "I'm logged in". |

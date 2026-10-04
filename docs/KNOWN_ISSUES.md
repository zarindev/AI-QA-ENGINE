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

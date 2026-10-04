# Storage

QA Pilot has **no database**. Everything is plain, pretty-printed JSON plus images/video under `workspace/`
(override the location with `QAP_WORKSPACE`). `backend/app/storage/repository.py` is the only code that
reads or writes these files.

```
workspace/
├── settings.json                       # UI overrides of config/settings.yaml (only changed keys)
├── .cache/ai/                          # cached Claude answers (safe to delete)
├── .locks/                             # lock files for concurrent writers (safe to delete when idle)
└── projects/<project-slug>/
    ├── project.json                    # Project: url, environment, authorization record, roles (no secrets)
    ├── secrets.enc                     # Fernet-encrypted role credentials and saved sessions
    ├── index.json                      # ProjectIndex: one RunSummary per run, for fast listing
    └── runs/<YYYYMMDD-HHMMSS>/
        ├── run.json                    # Run: mode, status, stages, progress, heartbeat, token usage
        ├── crawl/pages.json            # CrawlResult: pages + indexed elements, forms, tables, logs, per role
        ├── crawl/findings.json         # FindingsDoc: automatic-check findings, de-duplicated by symptom
        ├── artifacts/screenshots/crawl/<role>/PG-0001.png (+ .thumb.jpg)
        ├── artifacts/logs/events.jsonl # every progress event (feeds the live viewer)
        ├── executions/  replay/  artifacts/videos|clips/   (Phase 4)
        └── exports/crawl_report.html   # Phase 1 HTML report
```

## Rules

- **Atomic writes.** Data is written to a temp file in the same folder, `fsync`ed, then swapped in with
  `os.replace`. A crash never leaves a half-written JSON file.
- **Locks.** Each file has an in-process `RLock` plus a `filelock` lock in `workspace/.locks/`, so threads in the
  job executor and a second process (e.g. the CLI while the server runs) never interleave writes.
- **`schema_version`** is on every top-level document. Loading an older file runs the registered upgrades in
  `storage/migrations.py`; a file from a *newer* QA Pilot is refused with a clear message.
- **Relative paths.** Paths stored in JSON are relative to the run folder with forward slashes, so a project
  folder can be zipped, moved to another machine (or OS) and opened again.
- **Secrets.** Credentials and saved sessions live only in `secrets.enc`, encrypted with `QAP_SECRET_KEY` from
  `.env` (generated on first run). Moving a project to another machine needs the same key. Decrypted
  passwords and cookie values are registered for redaction and scrubbed from logs and captured page text.
- **Reset.** Deleting `workspace/` resets the app; deleting a project folder removes that project.

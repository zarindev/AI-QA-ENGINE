# Demo targets

Three small but realistic web apps, used to show and benchmark QA Pilot. Each keeps its data in one JSON file
(no database), has several roles, and contains **12–15 deliberately planted bugs**.

| App | URL | Roles (email / password) |
|---|---|---|
| CarePoint Clinic | http://localhost:8101 | admin@carepoint.test / Admin#2026 · dr.lee@carepoint.test / Doctor#2026 · reception@carepoint.test / Front#2026 |
| DriveNow Rentals | http://localhost:8102 | admin@drivenow.test / Admin#2026 · agent@drivenow.test / Agent#2026 · liam@drivenow.test / Drive#2026 |
| StockRoom POS | http://localhost:8103 | admin@stockroom.test / Admin#2026 · cashier@stockroom.test / Till#2026 |

These are fake accounts for local demo apps only.

```bash
./start_demos.sh            # macOS / Linux — all three, Ctrl+C stops them
start_demos.bat             # Windows — one window per app
./start_demos.sh --reset    # restore the seed data first
```

Each app also has a **Reset demo data** button in its footer (`POST /reset-demo-data`). Seed dates are relative to
the reset day, so the data never goes stale.

## Planted bugs

The answer keys are in `manifests/*_planted_bugs.json` (id, category, description, location, expected severity) and
each bug is marked in the source with `# PLANTED <ID>`. Categories: calculation / business rule, permission,
validation, data integrity, state transition, broken link, JavaScript error, broken image, UI / responsive and
accessibility.

**The QA Pilot engine never reads the manifests or the demo source.** It only sees what a browser sees. Only
`scripts/benchmark.py` (Phase 8) and `backend/tests/test_demo_apps.py` use the manifests: the test makes sure every
planted bug is still present, so the benchmark stays honest.

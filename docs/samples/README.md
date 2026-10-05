# Sample outputs

Real exports from QA Pilot's run `20261005-002110` on the **DriveNow Rentals** demo app (`demo_targets/car_rental_app`,
15 planted bugs; all names, plates and bookings are fictional demo data).

| File | What it is |
|---|---|
| [qa_report.pdf](qa_report.pdf) | Full QA report: cover, executive summary, Quality Score, charts, heatmap, permissions, one page per bug, appendices |
| [BUG-003.pdf](BUG-003.pdf) | Single-bug report: the missing 10 % weekly discount |
| [qa_report.xlsx](qa_report.xlsx) | Excel workbook: summary, requirements, stories, test cases, results, bugs, permission matrix, traceability |
| [bugs_jira.csv](bugs_jira.csv) | Jira CSV import |
| [pytest_suite.zip](pytest_suite.zip) | Exported pytest + Selenium Page Object suite — against the demo app after a data reset: 49 passed, 9 failed (all real bugs), 2 skipped |

Note: this run was recorded before screenshots carried privacy-blur regions, so these samples are not blurred.
That only matters for real personal data — newer runs blur emails, phone numbers and names in every export when
the project's privacy blur is on.

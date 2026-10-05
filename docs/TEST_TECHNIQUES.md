# Test techniques

QA Pilot designs tests with standard black-box techniques. Two designers work together:

- **Rules-based** (`backend/app/testdesign/rules_based.py`) — deterministic, free, built from what the crawl actually
  saw: pages, forms, field types and HTML constraints, which role reached which screen.
- **Claude** (`backend/app/testdesign/generator.py`, prompt `backend/app/ai/prompts/test_design.md`) — cases that need
  judgement: workflows, state machines, business rules with computed expected values, cross-module data checks.

Every case gets an ID `TC-<MODULE>-NNN`, a priority, preconditions, numbered steps with test data, an expected
result, and links to the stories / rules / workflows / pages it covers (the traceability matrix is built from these).
Nothing runs until a person approves it.

| Technique | Designer | What it checks | Example | Runs as |
|---|---|---|---|---|
| **Smoke** | rules | Every page each role can reach opens without an error page, login wall or JavaScript error | Doctor opens `/visits` — HTTP 200, no “Traceback” | rule runner (no AI) |
| **CRUD** | rules + Claude | A record can be created (and read back, edited, deleted where the UI allows it) | Create patient `QAP_Ann Lee` → appears in the list | AI agent |
| **E2E** | Claude | A workflow from start to finish across screens and roles | Book → check in → complete visit → invoice | AI agent |
| **Validation** | rules + Claude | Required fields and domain rules the HTML does not enforce | Phone `abc-123` is rejected | AI agent |
| **Boundary value** | rules | min/max/length limits just inside and just outside | Quantity 0, 1, max, max+1 | AI agent |
| **Equivalence partitioning** | rules | One valid and one invalid value per input class (email, number, date…) | Email `QAP_x@example.test` vs `not-an-email` | AI agent |
| **Negative** | Claude | Inputs that are obviously wrong for the domain | Return date before pickup date | AI agent |
| **State transition** | Claude | Every allowed transition, and every forbidden one is refused | Cancelled booking cannot be handed over | AI agent |
| **Permission** | rules + Claude | A role cannot open screens meant for other roles (direct URL), or other users’ records (changed id) | Receptionist opens `/reports` → must be refused | rule runner / AI agent |
| **Data integrity** | Claude | A change in one module shows up correctly everywhere else | Completing a visit updates the dashboard count and the invoice | AI agent |
| **Business rule** | Claude | Confirmed rules with concrete inputs and computed expected values; re-checked in Python | Fee 120.00, coverage 50 % → patient pays 60.00 | AI agent + Python recalculation |
| **UI / responsive** | rules | No horizontal scrolling at 768 px and 390 px | `/calendar` must fit a phone | rule runner |
| **Accessibility** | rules | axe-core WCAG 2 A/AA, critical and serious violations | Form inputs need labels; text contrast ≥ 4.5:1 | rule runner (bundled axe-core) |

## How a test is decided

1. **Rule runner** cases are pure Selenium checks with fixed criteria — no AI, no cost.
2. **AI agent** cases: Claude drives a real Chrome window one action at a time (click, type, select, assert…),
   every action passes the Safe Mode guard, and the agent finishes with pass / fail / blocked plus evidence.
3. **Failures are re-run** (default 2 more times) by replaying the recorded actions and re-judging the final page
   → reproducibility `3/3` (confirmed) or `1/3` (flaky → “Needs review”).
4. **Business rules are recalculated in Python**: Claude only reads the numbers off the page; a whitelisted
   evaluator computes the rule. A rule that does not hold fails the test even if the agent passed it.

## Test data

Generated with Faker and always recognisably fake: names start with `QAP_`, emails end with `@example.test`,
phone numbers use the reserved `+1 555 01xx` range. Tests that create, change or delete data are marked *Full Mode*;
in Safe Mode they are reported as **blocked**, never run.

## Multi-viewport

Any run can repeat the approved tests at tablet (768×1024) and phone (390×844) size; each repetition is reported
separately (`TC-APP-004@mobile`) and its bugs record the viewport.

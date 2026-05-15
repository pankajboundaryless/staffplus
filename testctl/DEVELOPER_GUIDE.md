# testctl — Developer Guide

Audience: Python developers maintaining or extending the testctl engine.
This document covers the internal architecture, data flow, complete YAML
reference, extension points, and design rationale.

---

## 1. What testctl is (and isn't)

testctl drives a **PHP web application over its real HTTP interface**, then
asserts state directly in **MariaDB**. It does not mock the database, patch
PHP internals, or use a headless browser.

This means:

- Every test exercises the full stack: routes → controllers → models → DB.
- Auth, CSRF, sessions, and middleware are all real.
- Tests are slower than unit tests but far more trustworthy for regression
  detection in a system with no unit-test coverage.
- JavaScript-heavy UI interactions that cannot be driven via HTTP require
  either an HTMX-style HTTP endpoint (which the app uses for ~95% of
  interactions) or a separate Playwright suite — testctl does not cover those.

---

## 2. High-level data flow

```
testctl run --impacted
        │
        ▼
 selector.py          ← reads modules.yaml, runs git diff
 (choose tests)
        │
        ▼
 data_engine.py       ← dump source DB → anonymize → create test DB
 (provision DB)
        │  test_db_name, anon_hash
        ▼
 runner.py            ← iterates test YAML files
        │
        ├─ for each test:
        │   ├─ db_performer.setup()   ← connect to test DB, run setup_sql
        │   ├─ http_performer.run()   ← drive HTTP steps, collect checks
        │   ├─ db_performer.run()     ← run DB validations, collect checks
        │   └─ db_performer.teardown()← run teardown_sql (always)
        │
        ▼
 result_router.py     ← write filesystem + HTML + webhook + Jira
        │
        ▼
 release_gate.py      ← APPROVED / REJECTED decision
        │
        ▼
 exit 0 (APPROVED) or exit 1 (REJECTED)   ← CI picks this up
```

---

## 3. Component reference

### 3.1 `cli.py`

Entry point. Built with [Click](https://click.palletsprojects.com/).

**Command groups:**
```
testctl run   --full | --changed | --impacted | --modules a,b
testctl gate  show <run_id> | approve <run_id> --reason "..."
testctl runs  list | show <run_id>
```

Config is loaded from `config/testctl.yaml` in the current directory.
All `${VAR}` references in the YAML are expanded from environment variables
(including a loaded `.env` file via `python-dotenv`).

The CLI passes a fully-resolved config dict to every downstream component.
Nothing reads environment variables directly after `cli.py`.

---

### 3.2 `engine/auth_helper.py`

Generates valid HS256 JWTs that the PHP application accepts.

```python
token = generate(
    secret="...",    # JWT_SECRET from app config
    uid=90001,       # auth_uid — must be unique per test user
    email="...",
    name="...",
    role="admin",
    roles=["admin"],
    aud="timetracker-ng",  # AUTH_APP_SLUG from app config
)
```

The JWT is posted to `/auth/callback`. PHP validates signature + `aud` + `exp`,
calls `syncUser()` (which creates a `users` + `people` row on first login),
and sets a session cookie. The `requests.Session` in the HTTP performer
carries this cookie for all subsequent requests in that test.

**Test user auth_uid values start at 90001** to avoid collisions with
anonymized production data (which uses real IDs starting at 1).

**Important:** The JWT secret and app slug must exactly match the values in
the PHP application's configuration. If they diverge, every test will 401.

---

### 3.3 `engine/data_engine.py`

Manages the test database lifecycle.

**Full flow:**
1. `_dump_source()` — `mariadb-dump --single-transaction` from the source DB.
2. `_create_db()` + `_import_dump()` — import into a staging DB
   (`testctl_staging_<run_id>`).
3. `_run_anonymization()` — apply rules from `anonymization.yaml` in-place
   on the staging DB.
4. `_export_dump()` — export anonymized staging to `anonymized_dump.sql`.
5. SHA-256 hash the dump file — stored in run metadata for audit.
6. `_create_db()` + `_import_dump()` — import into the final test DB
   (`testctl_run_<run_id>`).
7. Drop staging DB.

**Anonymization strategies** (see Section 6 for full reference):

| Strategy | Description |
|---|---|
| `constant` | Replace every row with a fixed literal |
| `suppress` | Set to NULL |
| `deterministic_name` | HMAC-SHA256 → `Prefix_NNNN` (same original → same result) |
| `deterministic_email` | HMAC-SHA256 → `local@domain` |
| `sequential` | `Prefix 1`, `Prefix 2`, … ordered by `id` |
| `numeric_range` | Deterministic value in [min, max]; supports `decimal_places` |
| `preserve_format` | Scramble digits, keep separators (e.g. `INV-2026-001 → INV-8312-647`) |
| `fake_iban` | Replace with syntactically valid fake IBAN |
| `fake_phone` | Replace with `+41000000000` |

**Why deterministic mappings?**
The same original value must always produce the same anonymized value
*within a run* to preserve foreign-key relationships. For example, if
`Person A` in `people` maps to `Person_1234`, any reference to `Person A`
in `employment_contracts` or `time_entries` must also resolve to `Person_1234`.
This is achieved via `HMAC-SHA256(seed + table:field:original)` cached in
`self._maps`.

---

### 3.4 `engine/runner.py`

Orchestrates one test run. For each test YAML file:

1. Instantiates `DbPerformer` and `HttpPerformer` with the current config.
2. Calls `db_performer.setup(test_case)` — connects to the test DB, runs
   `setup_sql` statements.
3. Calls `http_performer.run(test_case)` — executes all HTTP steps,
   collects `CheckResult` objects.
4. Shares the HTTP performer's `context` dict (populated by `extract:` steps)
   into the DB performer for use in `{{ var }}` lookups.
5. Calls `db_performer.run(test_case)` — executes DB validations.
6. Calls `db_performer.teardown(test_case)` — runs `teardown_sql`
   **unconditionally** (even if earlier steps failed).
7. Merges HTTP and DB checks into a single `TestResult`.

The runner records wall-clock duration per test and a per-test `Result`
enum value: `OK`, `NOK`, `SKIP`, or `ERROR`.

---

### 3.5 `performers/http_performer.py`

Drives the application over HTTP using `requests.Session`.

**Key behaviours:**

**Auth** (`_login`):
- Checks `self._logged_in_as` — avoids re-authenticating if the same role
  was used in a previous step.
- Generates JWT via `auth_helper.generate()`.
- POSTs to `/auth/callback` with `data={"token": jwt}`.
- Session cookie is maintained automatically by `requests.Session`.

**CSRF** (auto-injection):
- Before every POST (unless `skip_csrf: true`), the performer extracts
  `<input name="_csrf" value="...">` from `self._last_html` (the last
  GET response).
- If not found (e.g. first POST before any GET), it issues a GET to the
  same URL first to obtain the token.
- The token is injected as `body["_csrf"]`.
- The PHP app validates `$_POST['_csrf']` against `$_SESSION['_csrf_token']`.

**Context variables** (`{{ var }}`):
- `extract:` steps populate `self.context` from GET responses (CSS selector
  or regex).
- `from: location_header` in an `extract:` block reads from the `Location`
  header of the previous response (useful for getting the new resource ID
  from a 302 redirect).
- `_resolve()` / `_resolve_dict()` substitute `{{ var }}` in path and body
  values before each step is executed.

**Inline step validations** (`validations:` inside a step):
- `type: text_contains` / `type: text` — check whether `value` appears in
  the response body.
- `negate: true` — asserts the value does NOT appear (used for XSS tests).

**Location-header extraction:**
```yaml
- action: POST
  path: /things/new
  follow_redirect: false        # must be false to capture the Location header
  expect_status: 302
  extract:
    - name: thing_id
      regex: '/things/(\d+)'
      from: location_header     # regex applied to the Location: header value
```

---

### 3.6 `performers/db_performer.py`

Runs SQL-based assertions after HTTP steps complete.

**`setup(test_case)`:**
- Connects to the test DB using the `mariadb` Python connector.
- Executes each statement in `setup_sql` using `executemany` / separate
  `execute` calls.

**`run(test_case)`:**
For each `source: database` validation block:
1. Builds a `SELECT` query from `table` + `lookup` dict (all ANDed).
2. Applies `order_by` and `limit` (default 1).
3. If `expect_absent: true`: row must NOT exist → `OK`, row exists → `NOK`.
4. If row not found (and not `expect_absent`): adds a `NOK` check for
   `row_exists`.
5. If row found with no `expect` fields: adds an `OK` check for `row_exists`.
6. If row found with `expect` fields: compares each field using
   `validator.compare(expected, found, operator)`.

**`teardown(test_case)`:**
- Runs each statement in `teardown_sql`.
- Wraps in `try/except` so a teardown failure cannot mask a test failure.
- Called unconditionally — if the HTTP steps raise an exception, teardown
  still runs.

**Context sharing:**
The runner copies `http_performer.context` → `db_performer.context` after
HTTP steps complete. This allows `{{ var }}` extracted from HTTP responses
to be used in DB lookup conditions.

---

### 3.7 `engine/validator.py`

Comparison logic for DB field assertions.

| Operator | Meaning |
|---|---|
| `eq` (default) | `found == expected` (type-coerced to string) |
| `gte` | `float(found) >= float(expected)` |
| `lte` | `float(found) <= float(expected)` |
| `contains` | `str(expected) in str(found)` |
| `not_null` | `found is not None` |
| `is_null` | `found is None` |

---

### 3.8 `engine/selector.py`

Determines which test files to run based on the run mode.

| Mode | Logic |
|---|---|
| `--full` | All `tests/**/*.yaml` files |
| `--modules a,b` | Files under `tests/a/` and `tests/b/` |
| `--changed` | Git diff HEAD~1 → map changed files to modules → select those modules |
| `--impacted` | `--changed` + transitive downstream per `modules.yaml` |

The `modules.yaml` file maps each module name to glob patterns for source
files. When a source file appears in `git diff --name-only HEAD~1`, its
module (and optionally its downstream modules) are selected.

---

### 3.9 `engine/result_router.py`

Routes a `RunResult` to one or more configured endpoints.

**Built-in drivers:**

| Driver | What it writes |
|---|---|
| `filesystem` | `metadata.json`, `result.json`, `junit.xml` under `runs/<run_id>/` |
| `html_report` | `report.html` — C-Level summary (always alongside filesystem) |
| `webhook` | HTTP POST with `{"run_id", "decision", "summary", "failures"}` |
| `jira` | Creates one Bug per NOK test in the configured Jira project |

**Adding a new driver:**
1. Add `def _mydriver(self, run: RunResult, ep: dict, run_dir: Path)` to
   `ResultRouter`.
2. Add `elif driver == "mydriver":` in `route()`.
3. Add the endpoint config to `config/endpoints.yaml` in testctl-tests.

---

### 3.10 `engine/release_gate.py`

Evaluates whether a run APPROVES or REJECTS deployment.

**Decision logic (in order):**
1. If any test in a `critical_modules` module is `NOK` or `ERROR` →
   **REJECTED** regardless of `max_failures`.
2. If total `NOK + ERROR` count > `max_failures` → **REJECTED**.
3. Otherwise → **APPROVED**.

**Manual override:**
```bash
testctl gate approve 20260507_143022 --reason "Flaky network test, prod verified"
```
This writes an `override` record into `release_decision.json`. The record
includes timestamp, operator (git user), and reason — it is intentionally
immutable (no delete command) for audit purposes.

---

### 3.11 `reporters/html_report.py`

Generates a self-contained HTML file (`report.html`) with:
- Decision badge (green APPROVED / red REJECTED)
- Per-module pass/fail status table
- Failures table (test name, check ID, field, expected, found)
- Run metadata (run ID, git commit, timing, anonymization hash)

The HTML is fully inline (no external assets) so it can be emailed or
attached to a Jira ticket.

---

## 4. YAML test format — complete reference

```yaml
# ── Header ────────────────────────────────────────────────────────────────────
test_case: unique_snake_case_identifier   # required; used as check_id prefix
module: time                              # required; must be a key in modules.yaml

# ── Auth ──────────────────────────────────────────────────────────────────────
auth:                                     # omit for unauthenticated tests
  role: employee                          # key in testctl.yaml auth.test_users

# ── DB setup ──────────────────────────────────────────────────────────────────
setup_sql:                                # optional; runs before HTTP steps
  - "INSERT IGNORE INTO ..."              # use INSERT IGNORE to be idempotent
  - >                                     # multi-line SQL with YAML block scalar
    INSERT IGNORE INTO table (a, b)
    SELECT ... FROM other_table

# ── HTTP steps ────────────────────────────────────────────────────────────────
steps:
  - action: GET                           # GET or POST (PUT/PATCH/DELETE not yet implemented)
    path: /some/path                      # relative to base_url; {{ var }} resolved
    expect_status: 200                    # optional; adds a status_code check

    # Extract values into context variables (GET and POST both supported)
    extract:
      - name: my_var                      # variable name for {{ my_var }}
        selector: "CSS selector"          # CSS selector (BeautifulSoup select_one)
        attribute: value                  # HTML attribute to read; "text" = inner text
      - name: id_from_redirect
        regex: '/things/(\d+)'            # regex on response body (or location header)
        from: location_header             # optional; applies regex to Location: header
                                          # requires follow_redirect: false on same step

    # Inline validations (checked against this step's response body)
    validations:
      - type: text_contains               # text_contains | text
        value: "Expected string"
      - type: text_contains
        value: "Should not appear"
        negate: true                      # asserts value is NOT present

  - action: POST
    path: /things/new
    follow_redirect: false                # default: true; set false to capture Location
    expect_status: 302
    skip_csrf: false                      # default: false; set true to test CSRF rejection

    body:
      field_name: "literal value"
      other_field: "{{ my_var }}"         # context variable substitution

# ── DB validations ────────────────────────────────────────────────────────────
validations:
  - source: database
    table: things
    lookup:                               # all fields ANDed in WHERE clause
      tenant_id: 1
      name:      "expected name"
      field:     "{{ my_var }}"           # context variables work here too
    order_by: id DESC                     # optional; default: no ordering
    limit:    1                           # optional; default: 1

    expect:                               # omit to just assert the row exists
      status: active
      amount: "150.00"                    # values compared as strings by default

    operators:                            # optional per-field operator overrides
      amount: gte                         # eq (default) | gte | lte | contains
                                          # not_null | is_null

    expect_absent: true                   # assert NO row matches the lookup
                                          # (mutually exclusive with expect/operators)

  - source: http                          # check rendered HTML from a GET
    path: /things
    selector: ".thing-row"
    expect:
      count_gte: 1                        # count_gte | count_eq | text | text_contains
                                          # | exists

# ── DB teardown ───────────────────────────────────────────────────────────────
teardown_sql:                             # always runs, even if test fails
  - "DELETE FROM things WHERE name = 'expected name'"
  - >
    DELETE FROM related WHERE thing_id IN
    (SELECT id FROM things WHERE name = 'expected name')
```

---

## 5. Context variables

Context variables are set by `extract:` blocks and shared across steps and
into DB validations. They are resolved at execution time, not parse time.

**Sources:**

| Source | How to populate |
|---|---|
| CSS selector | `selector: "select[name='x'] option:first-child"` + `attribute: value` |
| Regex on body | `regex: 'csrf.*?value="([^"]+)"'` |
| Regex on Location header | `regex: '/resource/(\d+)'` + `from: location_header` |

**Usage:**
- In `path`: `path: /things/{{ thing_id }}/edit`
- In `body` values: `customer_id: "{{ first_customer_id }}"`
- In DB `lookup` values: `lookup: {id: "{{ thing_id }}"}`

**Scope:** Context is per-test-case. It is not shared between test cases.

---

## 6. Anonymization strategy reference

Configured in `config/anonymization.yaml`. Applied once per run to the
staging DB copy before tests start.

```yaml
seed: "${ANON_SEED}"   # change per environment; drives all deterministic mappings

rules:
  - table: people
    fields:
      first_name:
        strategy: deterministic_name
        prefix: Person              # → "Person_4291"

      last_name:
        strategy: suppress          # → NULL

      email:
        strategy: deterministic_email
        domain: example.test        # → "user_7823@example.test"

      salary:
        strategy: numeric_range
        min: 50000
        max: 150000                 # integer; deterministic per original value
        # decimal_places: 2         # add to produce decimal output e.g. 75423.17

      reference:
        strategy: preserve_format   # "INV-2026-001" → "INV-8312-647"

      phone:
        strategy: fake_phone        # → "+41000000000"

      iban:
        strategy: fake_iban         # → "CH5604835012345678009"

      notes:
        strategy: constant
        value: "Test notes"         # every row set to the same literal
```

**Determinism guarantee:** Within a single run, the same original value for
`table:field` always maps to the same anonymized value. This preserves FK
integrity (e.g. a person's name in `people` and in `time_entries` will both
map to the same fake name).

**Adding a new strategy:**
1. Add a new `elif strategy == "myname":` branch in
   `DataEngine._anonymize_field()`.
2. The branch receives `conn` (mariadb connection), `table`, `field`, and
   `cfg` (the YAML dict for this field).
3. Use `conn.cursor()` to `SELECT id, field FROM table`, map each row, and
   `UPDATE` back.

---

## 7. Extension points

### Adding a new result driver

```python
# In result_router.py:
def _slack(self, run: RunResult, ep: dict, run_dir: Path) -> None:
    import urllib.request, json
    payload = {"text": f"*{run.release_decision}* — {run.passed}/{run.total} passed"}
    req = urllib.request.Request(
        ep["url"],
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=10)

# Then in route():
elif driver == "slack":
    self._slack(run, ep, run_dir)
```

```yaml
# In config/endpoints.yaml:
- driver: slack
  enabled: true
  url: "${SLACK_WEBHOOK_URL}"
```

---

### Adding a new performer

Create `testctl/performers/myperformer.py` inheriting from `BasePerformer`:

```python
from .base import BasePerformer
from ..models.results import CheckResult, Result, TestResult

class MyPerformer(BasePerformer):
    def setup(self) -> None: ...
    def teardown(self) -> None: ...
    def run(self, test_case: dict) -> TestResult: ...
```

Register it in `runner.py` by instantiating it and merging its checks into
the final `TestResult`.

---

### Supporting PUT / PATCH / DELETE steps

In `http_performer.py`, the else-branch for non-GET methods handles POST.
To add PUT:
```python
resp = self.session.request(
    method, url, data=body,       # method is already uppercased from step["action"]
    allow_redirects=follow, timeout=15,
)
```
No change needed — `method` is already passed through to `session.request()`.
The only gap is that PUT/PATCH forms rarely exist in this PHP app (it uses
POST + `_method` override), so the CSRF injection logic handles POST only.

---

## 8. Design decisions and known limitations

**Why `requests` and not Playwright?**
The application uses HTMX for dynamic UI, meaning every interaction is a
real HTTP request. A headless browser would add ~10× startup overhead for no
coverage gain. The ~5% of interactions that require JavaScript (e.g. drag-
and-drop board columns) are not currently tested by testctl.

**Why HS256 JWT generation instead of a test login endpoint?**
The app has no dedicated test backdoor. Generating JWTs that match the
production auth flow is the only way to create real authenticated sessions
without modifying the application code.

**Why separate test DB per run rather than rollback?**
PHP tests against a live session that holds a DB connection. MariaDB
transactions cannot span an HTTP request/response cycle without connection
pooling. Separate DBs give complete isolation with zero coordination overhead.

**Why `INSERT IGNORE` in setup_sql?**
Tests are designed to be re-runnable. If a previous run's teardown failed,
`INSERT IGNORE` prevents a duplicate-key error from blocking the next run.
IDs in the 99xxx range are reserved for test fixtures to avoid any collision
with anonymized production data.

**Why is teardown always run?**
If an HTTP step returns an unexpected status and the test is marked NOK,
teardown must still clean up the fixture rows it inserted. Leaving test
fixtures behind corrupts subsequent runs. The runner uses `try/finally`
semantics for teardown.

**Decimal support in `numeric_range`:**
The `decimal_places` parameter scales min/max by `10^n`, applies the integer
hash, then divides back. This gives deterministic decimal values without
floating-point entropy. Example: `min: 50, max: 400, decimal_places: 2`
generates values like `142.37`.

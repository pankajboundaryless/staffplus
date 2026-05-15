# testctl-tests — Boundaryless Test Suite

Test cases and configuration for the Boundaryless Management Platform,
executed by the [testctl](../testctl) engine.

## Quick start

```bash
# 1. Install the engine (once per server)
pip install -e ../testctl

# 2. Copy and fill in environment variables
cp .env.example .env
# edit .env — see variables below

# 3. Run the full test suite
testctl run --full

# 4. Run only changed modules (CI workflow)
testctl run --changed

# 5. Run changed + downstream
testctl run --impacted

# 6. Run specific modules
testctl run --modules time,invoicing

# 7. Check the release decision
testctl gate show 20260507_143022

# 8. Manually approve a rejected run
testctl gate approve 20260507_143022 --reason "Known flaky test, manually verified"
```

## Environment variables (.env)

```
TEST_BASE_URL=http://localhost          # URL of the test app instance
DB_HOST=localhost
DB_USER=testctl_user
DB_PASSWORD=your-db-password
DB_NAME=management_dev                  # source database to anonymize

JWT_SECRET=your-jwt-hs256-secret        # must match JWT_SECRET in app/.env.php
AUTH_APP_SLUG=timetracker-ng            # must match AUTH_APP_SLUG in app/.env.php

ANON_SEED=change-this-to-a-random-string

# Optional: override the runs output directory
TESTCTL_RUNS_DIR=./runs

# Optional: result endpoints
JIRA_URL=https://yourorg.atlassian.net
JIRA_PROJECT_KEY=BND
JIRA_TOKEN=your-jira-token
RELEASE_WEBHOOK_URL=https://your-cicd/webhook/testctl
WEBHOOK_SECRET=your-webhook-secret
SLACK_WEBHOOK_URL=https://hooks.slack.com/...
```

## Directory structure

```
testctl-tests/
├── config/
│   ├── testctl.yaml         # Main config (app URL, DB, auth, release gate)
│   ├── modules.yaml         # Module → file path → downstream mapping
│   ├── anonymization.yaml   # Field-level anonymization rules
│   └── endpoints.yaml       # Result routing (filesystem, Jira, webhook, HTML)
├── tests/
│   ├── auth/                # Auth flow, permission enforcement
│   ├── people/              # People CRUD
│   ├── projects/            # Project management
│   ├── time/                # Time booking, approval workflow
│   ├── absence/             # Absence requests
│   ├── invoicing/           # Invoice creation, rate cards
│   ├── approvals/           # Token-based deep-link approval
│   └── security/            # CSRF, tenant isolation, auth bypass
└── runs/                    # Run output (git-ignored, created at runtime)
    └── <run_id>/
        ├── metadata.json
        ├── result.json
        ├── junit.xml
        ├── report.html      # C-Level HTML report
        ├── anonymized_dump.sql
        └── release_decision.json
```

## Test YAML format

```yaml
test_case: descriptive_snake_case_name   # required, unique
module: time                              # must match a key in modules.yaml
auth:
  role: employee                          # test user role (defined in testctl.yaml)

setup_sql:                                # SQL run before the test (optional)
  - "INSERT INTO ..."

steps:
  - action: GET
    path: /time
    expect_status: 200
    extract:                              # capture values into context variables
      - name: csrf_token
        selector: "input[name='_csrf']"
        attribute: value

  - action: POST
    path: /time/store
    skip_csrf: false                      # set true to test CSRF rejection
    body:
      project_id: "{{ project_id }}"     # {{ var }} references context variables
      date: "2026-05-07"
      hours: "8"
    follow_redirect: true
    expect_status: 302

validations:
  - source: database                      # check DB state after HTTP steps
    table: time_entries
    lookup:
      project_id: "{{ project_id }}"
      date: "2026-05-07"
    order_by: id DESC
    limit: 1
    expect:
      hours: 8.00
      status: draft
    operators:                            # optional per-field comparison ops
      hours: eq                           # eq (default), gte, lte, contains, not_null, is_null

  - source: http                          # check rendered HTML
    path: /time
    selector: ".time-entry-row"
    expect:
      count_gte: 1                        # count_gte, count_eq, text, text_contains, exists

teardown_sql:                             # SQL run after the test (always runs)
  - "DELETE FROM time_entries WHERE ..."
```

## Run output

Every run produces a self-contained audit directory under `runs/<run_id>/`:

| File | Contents |
|---|---|
| `metadata.json` | Run ID, git commit, mode, modules, timing |
| `result.json` | Full structured results per test case with expected/found per check |
| `junit.xml` | JUnit format for CI systems |
| `report.html` | C-Level HTML summary (decision, module status, failures) |
| `anonymized_dump.sql` | The anonymized DB used for this run (sha256-hashed) |
| `release_decision.json` | APPROVED / REJECTED + reason + manual override record |

## CI/CD integration

```yaml
# Example GitHub Actions step
- name: Run test suite
  run: |
    cd testctl-tests
    testctl run --impacted
  env:
    TEST_BASE_URL: http://test-app
    DB_HOST: localhost
    DB_USER: testctl
    DB_PASSWORD: ${{ secrets.DB_PASSWORD }}
    DB_NAME: management_dev
    JWT_SECRET: ${{ secrets.JWT_SECRET }}
    AUTH_APP_SLUG: timetracker-ng
    ANON_SEED: ${{ secrets.ANON_SEED }}

# testctl exits 0 on APPROVED, 1 on REJECTED — CI picks this up automatically.
```

## Module coverage status

| Module | Tests | Status |
|---|---|---|
| auth | 3 | starter set |
| people | 2 | starter set |
| projects | 1 | starter set |
| time | 2 | starter set |
| absence | 1 | starter set |
| invoicing | 2 | starter set |
| approvals | 1 | starter set |
| security | 3 | starter set |
| reports | 0 | gap — add next |
| tasks | 0 | gap — browser tests needed |
| planning | 0 | gap |
| holidays | 0 | gap |
| admin | 0 | gap — add role/permission tests |

Coverage gaps are reported in `report.html` but do not block the release
gate unless the module is in `critical_modules` in `testctl.yaml`.

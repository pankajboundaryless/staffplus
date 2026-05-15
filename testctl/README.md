# testctl — Boundaryless Test Control Engine

A modular, auditable test orchestration tool for PHP web applications.
Drives the application entirely via HTTP, validates state in MariaDB,
and routes structured results to any configured endpoint.

## Architecture

```
testctl/
├── testctl/
│   ├── cli.py               # click CLI — entry point
│   ├── engine/
│   │   ├── auth_helper.py   # HS256 JWT generation for test users
│   │   ├── data_engine.py   # SQL dump → anonymize → provision test DB
│   │   ├── runner.py        # Orchestrate performers per test file
│   │   ├── selector.py      # Choose tests: changed / impacted / modules / full
│   │   ├── validator.py     # compare(expected, found, op)
│   │   ├── result_router.py # Route results to filesystem / webhook / Jira / HTML
│   │   └── release_gate.py  # APPROVED / REJECTED decision + audit record
│   ├── performers/
│   │   ├── http_performer.py  # Python requests — drives HTTP layer + CSRF
│   │   └── db_performer.py    # Direct MariaDB assertions
│   └── reporters/
│       └── html_report.py     # C-Level HTML summary report
└── pyproject.toml
```

## Installation

```bash
# On the test server (Linux), install once:
pip install -e /path/to/testctl

# Or from a private git repo:
pip install git+ssh://git@github.com/boundaryless/testctl.git
```

Dependencies: `click`, `requests`, `beautifulsoup4`, `mariadb`, `PyYAML`, `python-dotenv`

The `mariadb` package requires the MariaDB C connector:
```bash
apt install libmariadb-dev   # Debian/Ubuntu
yum install mariadb-devel    # RHEL/CentOS
```

## Test configuration repo

This package is the engine only. All test cases and config live in a
separate repo (`testctl-tests`). Run `testctl` commands from inside that
repo directory.

## Adding a new result endpoint

1. Add a method `_mydriver(self, run, ep, run_dir)` in `result_router.py`
2. Add a `elif driver == "mydriver":` branch in `route()`
3. Add the endpoint entry to `config/endpoints.yaml` in testctl-tests

## Auth strategy

The engine generates valid HS256 JWTs (matching the app's `jwt_secret`)
and POSTs them to `/auth/callback`. PHP validates, runs `syncUser()`,
and creates a session. Test users are created on-the-fly in the test DB
with high `auth_uid` values (90001+) to avoid conflicts with anonymized
production data.

CSRF tokens are automatically extracted from GET responses and injected
into POST bodies. Use `skip_csrf: true` on a step to test CSRF rejection.

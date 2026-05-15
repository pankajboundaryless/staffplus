# Boundaryless Test Suite — Test Manual

This document describes every test case in the suite, the data conventions
they follow, how to run them, and how to write new ones.

---

## 1. Test users

Four test users are pre-configured in `config/testctl.yaml`. They are
**created on-the-fly** in the test DB the first time they authenticate —
no manual DB seeding is required.

| Role | auth_uid | Email | Permissions |
|---|---|---|---|
| `admin` | 90001 | testadmin@example.test | Full access |
| `project_manager` | 90002 | testpm@example.test | Projects + time approval |
| `employee` | 90003 | testemployee@example.test | Own time + absence only |
| `line_manager` | 90004 | testmanager@example.test | Team management |

**auth_uid values start at 90001** to guarantee no collision with anonymized
production data (real IDs start at 1 and are typically in the low thousands).

---

## 2. Fixture ID conventions

Tests that need pre-seeded rows use IDs in the **99xxx range**:

| Range | Purpose |
|---|---|
| 99001–99099 | Projects seeded by test setup |
| 99801–99899 | Entities (people, invoices, absence requests) seeded by test setup |
| 99901–99999 | Approval requests / steps seeded by test setup |

All setup rows use `INSERT IGNORE` so the test is safe to re-run if a
previous teardown failed.

---

## 3. Test case catalog

### Module: `auth`

---

#### `auth_login_flow`
**File:** `tests/auth/test_login_flow.yaml`
**Role:** admin

Verifies that the JWT auth callback produces a valid session.

| Step | What happens |
|---|---|
| GET `/dashboard` (pre-auth) | Expects 302 redirect to login |
| POST `/auth/callback` with JWT | Expects 302 redirect on success |
| GET `/dashboard` (post-auth) | Expects 200 — session is live |

No DB validations. No setup/teardown.

---

#### `auth_permission_enforcement`
**File:** `tests/auth/test_permission_enforcement.yaml`
**Role:** employee

Verifies that a low-privilege user cannot access admin-only pages.

| Step | What happens |
|---|---|
| GET `/admin/users` | Expects 302 or 403 — employee lacks `admin.users` permission |
| GET `/admin/roles` | Same |

No DB validations.

---

#### `auth_basic`
**File:** `tests/auth/test_auth.yaml`
**Role:** admin

Smoke test: authenticated user can load the dashboard.

| Step | What happens |
|---|---|
| GET `/dashboard` | Expects 200 |

---

### Module: `people`

---

#### `people_list_accessible`
**File:** `tests/people/test_people_list.yaml`
**Role:** admin

Verifies the people index page loads and lists at least one person.

| Step | What happens |
|---|---|
| GET `/people` | Expects 200 |

**DB validation:** `people` table, `tenant_id = 1`, at least 1 row.

---

#### `people_create_person`
**File:** `tests/people/test_create_person.yaml`
**Role:** admin

Creates a new person via the form.

| Step | What happens |
|---|---|
| GET `/people/new` | Loads form, expects 200 |
| POST `/people/new` | Submits `first_name`, `last_name`, `email`, `status` |

**Body fields:** `first_name`, `last_name`, `email`, `status`

**DB validation:** Row in `people` with `email = testperson@example.test`,
`status = active`.

**Teardown:** Deletes the created person by email.

---

### Module: `projects`

---

#### `projects_create_project`
**File:** `tests/projects/test_create_project.yaml`
**Role:** admin

Creates a new billable project.

| Step | What happens |
|---|---|
| GET `/projects/new` | Loads form |
| POST `/projects/new` | Submits `name`, `type: billable`, `status: active` |

**DB validation:** Row in `projects` with `name = Testctl Test Project`,
`type = billable`.

**Teardown:** Deletes the project by name.

---

### Module: `time`

---

#### `time_create_entry`
**File:** `tests/time/test_create_entry.yaml`
**Role:** employee

Books a time entry for a specific date.

**Setup:** Seeds project 99002 and adds the employee as a project member.

| Step | What happens |
|---|---|
| GET `/time/book` | Loads the time booking page |
| POST `/time/book` | Submits `project_id`, `date_worked`, `duration`, `description` |

**Body fields:** `project_id`, `date_worked: 2026-05-07`, `duration: 2:00`,
`description`

**DB validation:** Row in `time_entries`, `date_worked = 2026-05-07`,
`status = draft`.

**Teardown:** Deletes the entry, project member, and project.

---

#### `time_submit_week_creates_approval`
**File:** `tests/time/test_approval_workflow.yaml`
**Role:** employee

Submits a full week of time for approval. Verifies the entry status
transitions from `draft` to `submitted`.

**Setup:** Seeds project 99002 + project member + a pre-seeded time entry
(id 99801, `date_worked = 2026-05-04`, `status = draft`).

| Step | What happens |
|---|---|
| GET `/time/book` | Loads booking page |
| POST `/time/submit-week` | Submits `week_start: 2026-05-04`, `week_end: 2026-05-10` |

**DB validation:** `time_entries` id=99801, `status = submitted`.

**Teardown:** Deletes approval steps, approval requests, time entry, project
member, and project.

---

#### `time_timer_start_stop_convert`
**File:** `tests/time/test_timer_workflow.yaml`
**Role:** employee

Full timer lifecycle: start → stop → convert to a time entry.

**Setup:** Seeds project 99003 + project member for the employee user.

| Step | What happens |
|---|---|
| GET `/time/timer` | Loads timer page |
| POST `/time/timer/start` | `project_id: 99003`, `description: Testctl timer session` → returns `{"session_id": N}` |
| POST `/time/timer/stop` | `session_id: {{ session_id }}` |
| POST `/time/timer/convert` | `session_id`, `project_id: 99003`, `date_worked: 2026-05-07`, `minutes: 30` |

**Extraction:** `session_id` extracted via regex `"session_id"\s*:\s*(\d+)` from
the JSON response of the start step.

**DB validation:** Row in `time_entries`, `date_worked = 2026-05-07`,
`description = Testctl converted timer entry`, `status = draft`.

**Teardown:** Deletes time entry, timer session, project member, project.

---

### Module: `absence`

---

#### `absence_create_request`
**File:** `tests/absence/test_absence_request.yaml`
**Role:** employee

Submits an absence request via the request form.

| Step | What happens |
|---|---|
| GET `/absence/request` | Loads request form |
| POST `/absence/request` | `absence_type_id: 1`, `start_date: 2026-06-01`, `end_date: 2026-06-03` |

**DB validation:** Row in `absence_requests`, `start_date = 2026-06-01`,
`end_date = 2026-06-03`, `status = pending`.

**Teardown:** Deletes absence days, approval steps/requests, and the
absence request.

> **Note:** `absence_type_id: 1` assumes a standard leave type exists with
> id=1 in the anonymized DB. If your test DB has a different layout,
> update this value or extract it dynamically with a selector.

---

#### `absence_approve_request`
**File:** `tests/absence/test_absence_approve.yaml`
**Role:** admin (requires `absence.approve` permission)

Approves a pre-seeded pending absence request.

**Setup:** Seeds absence request id=99801 linked to the employee user
(auth_uid 90003), `status = pending`.

| Step | What happens |
|---|---|
| POST `/absence/approve` | `request_id: 99801` |

**DB validation:** `absence_requests` id=99801, `status = approved`.

**Teardown:** Deletes absence days, time entries, and the absence request.

---

### Module: `invoicing`

---

#### `invoicing_rate_card_list_accessible`
**File:** `tests/invoicing/test_rate_card.yaml`
**Role:** admin

Verifies the rate cards list page loads and has at least one rate card
in the DB.

| Step | What happens |
|---|---|
| GET `/invoicing/rate-cards` | Expects 200 |

**DB validation:** Row in `rate_cards`, `tenant_id = 1`.

---

#### `invoicing_create_draft_invoice`
**File:** `tests/invoicing/test_invoice_create.yaml`
**Role:** admin

Creates a new draft invoice.

| Step | What happens |
|---|---|
| GET `/invoicing/new` | Loads form; extracts `first_customer_id` from customer dropdown |
| POST `/invoicing/new` | `customer_id`, `invoice_date: 2026-05-07`, `due_date: 2026-06-07`, `currency: CHF` |

**Extraction:** `first_customer_id` from `select[name='customer_id'] option:not([value=''])`.

**DB validation:** Row in `invoices`, `invoice_date = 2026-05-07`,
`currency = CHF`, `status = draft`.

**Teardown:** Deletes invoice lines and invoice.

---

#### `invoicing_record_payment`
**File:** `tests/invoicing/test_invoice_payment.yaml`
**Role:** admin

Records a payment against a pre-seeded invoice.

**Setup:** Seeds invoice id=99901 linked to the first customer,
`status = sent`, `total = 1000.00`, `amount_paid = 0.00`.

| Step | What happens |
|---|---|
| POST `/invoicing/99901/action` | `action: record_payment`, `amount: 1000.00`, `currency: CHF`, `paid_at: 2026-05-07` |

**DB validation:** `invoices` id=99901, `status = paid`, `amount_paid = 1000.00`.

**Teardown:** Deletes payment transactions and invoice.

---

#### `invoicing_cross_charge_form_accessible`
**File:** `tests/invoicing/test_cross_charge.yaml`
**Role:** admin

Verifies the cross-charge invoice form loads.

| Step | What happens |
|---|---|
| GET `/invoicing/cross-charge/new` | Expects 200, page contains "Cross-Charge" |

> **Note:** Full cross-charge generation requires at least 2 legal entities
> with a shared rate card. The create step is not automated in this test
> as the fixture data varies per environment.

---

### Module: `approvals`

---

#### `approvals_token_deeplink_respond`
**File:** `tests/approvals/test_token_approval.yaml`
**Role:** None (unauthenticated — token-based)

Tests the email deep-link approval flow. The approver clicks a link in
their email which hits the app without a session.

**Setup:** Seeds approval request id=99901 and approval step id=99901
with known tokens.

| Step | What happens |
|---|---|
| GET `/approvals/respond?token=testctl-step-token-xyz789&action=approve` | `follow_redirect: false`, expects 302 |

**DB validation:** `approval_steps` id=99901, `status = approved`.

**Teardown:** Deletes the approval step and request.

---

### Module: `customers`

---

#### `customers_create_customer`
**File:** `tests/customers/test_create_customer.yaml`
**Role:** admin

Creates a new customer.

| Step | What happens |
|---|---|
| GET `/customers/new` | Loads form |
| POST `/customers/new` | `name`, `short_name`, `type: customer`, `currency: CHF`, `payment_terms_days: 30` |

**DB validation:** Row in `customers`, `name = Testctl Test Customer`,
`status = active`.

**Teardown:** Deletes billing profile and customer.

---

#### `customers_add_contact`
**File:** `tests/customers/test_customer_contacts.yaml`
**Role:** admin

Adds a contact to a pre-seeded customer.

**Setup:** Seeds customer id=99801 and its billing profile.

| Step | What happens |
|---|---|
| GET `/customers/99801` | Loads customer detail page |
| POST `/customers/99801/contact` | `first_name: Test`, `last_name: Contact`, `email`, `job_title` |

**DB validation:** Row in `customer_contacts`, `customer_id = 99801`,
`email = testcontact@testctl.local`.

**Teardown:** Deletes contacts, billing profile, and customer.

---

### Module: `products`

---

#### `products_create_product`
**File:** `tests/products/test_create_product.yaml`
**Role:** admin

Creates a new billable product/service.

| Step | What happens |
|---|---|
| GET `/products/new` | Loads form |
| POST `/products/new` | `name`, `unit: hour`, `default_sale_price: 150.00`, `status: active` |

**DB validation:** Row in `products`, `name = Testctl Test Product`,
`default_sale_price = 150.00`, `status = active`.

**Teardown:** Deletes product.

---

### Module: `subscriptions`

---

#### `subscriptions_create_subscription`
**File:** `tests/subscriptions/test_create_subscription.yaml`
**Role:** admin

Creates a new recurring subscription.

| Step | What happens |
|---|---|
| GET `/subscriptions/new` | Loads form; extracts `first_customer_id` |
| POST `/subscriptions/new` | `customer_id`, `name: Testctl Monthly Retainer`, `start_date: 2026-06-01`, `billing_interval_value: 1`, `billing_interval_unit: month`, `currency: CHF` |

**DB validation:** Row in `subscriptions`, `name = Testctl Monthly Retainer`,
`status = active`, `currency = CHF`.

**Teardown:** Deletes subscription lines and subscription.

---

### Module: `planning`

---

#### `planning_create_assignment`
**File:** `tests/planning/test_resource_assignment.yaml`
**Role:** admin

Assigns a person to a project in the resource plan.

**Setup:** Seeds project id=99004.

| Step | What happens |
|---|---|
| GET `/planning` | Loads planning board; extracts `first_person_id` |
| POST `/planning/assign` | `project_id: 99004`, `person_id: {{ first_person_id }}`, `start_date: 2026-06-01`, `end_date: 2026-06-30`, `allocation_pct: 100` |

**DB validation:** Row in `resource_plan_assignments`, `project_id = 99004`,
`status = draft`, `allocation_pct = 100.00`.

**Teardown:** Deletes project members, approval steps/requests (if
absence conflict triggers one), resource plan assignments, and project.

---

### Module: `tasks`

---

#### `tasks_create_board_and_task`
**File:** `tests/tasks/test_task_workflow.yaml`
**Role:** admin

Creates a task board, then creates a task on it. Uses Location-header
extraction to chain the two steps.

| Step | What happens |
|---|---|
| GET `/tasks` | Loads tasks index |
| POST `/tasks/board/new` | `name: Testctl Board`, `type: custom`; `follow_redirect: false`; extracts `board_id` from `Location: /tasks/board/N` header |
| GET `/tasks/board/{{ board_id }}` | Loads board; extracts `first_col_id` from `[data-column-id]` attribute |
| POST `/tasks/task/new` | `board_id`, `column_id`, `title: Testctl Test Task`, `priority: medium` |

**DB validation:** Row in `board_tasks`, `title = Testctl Test Task`,
`priority = medium`.

**Teardown:** Deletes task assignments, tasks, board columns, and board.

---

### Module: `holidays`

---

#### `holidays_create_calendar_with_entry`
**File:** `tests/holidays/test_holiday_calendar.yaml`
**Role:** admin

Creates a holiday calendar, then adds an entry to it.

| Step | What happens |
|---|---|
| GET `/holidays` | Loads calendar list |
| POST `/holidays/new` | `name`, `type: custom`, `year: 2026`, `color`; `follow_redirect: false`; extracts `calendar_id` from Location header |
| POST `/holidays/{{ calendar_id }}/entry/new` | `date: 2026-08-01`, `name: Testctl National Day` |

**DB validations:**
- `holiday_calendar_sets` — `name = Testctl Holiday Calendar`, `type = custom`.
- `holiday_calendar_entries` — `name = Testctl National Day`, `date = 2026-08-01`.

**Teardown:** Deletes entries and the calendar set.

---

### Module: `legal_entities`

---

#### `legal_entities_create_entity`
**File:** `tests/legal_entities/test_legal_entity.yaml`
**Role:** admin

Creates a new legal entity.

| Step | What happens |
|---|---|
| GET `/legal-entities/new` | Loads form |
| POST `/legal-entities/new` | `name`, `legal_name`, `type: internal`, `currency: CHF`, `payment_terms_days: 30`, `status: active` |

**DB validation:** Row in `legal_entities`, `name = Testctl Legal Entity`,
`type = internal`, `status = active`.

**Teardown:** Deletes legal entity by name.

---

### Module: `admin`

---

#### `admin_settings_save`
**File:** `tests/admin/test_admin_settings.yaml`
**Role:** admin

Saves tenant settings (timezone, currency, invoice prefix, etc.).

| Step | What happens |
|---|---|
| GET `/admin/settings` | Loads settings page |
| POST `/admin/settings` | `timezone: Europe/Zurich`, `default_currency: CHF`, `invoice_prefix: INV-`, etc. |

**DB validation:** Row in `tenant_settings`, `setting_key = default_currency`,
`value = CHF`.

> **Note:** This test writes to the live tenant settings table. It is
> idempotent (sets to known values) but avoid running it in an environment
> where the settings must not change.

---

#### `admin_create_role`
**File:** `tests/admin/test_admin_role.yaml`
**Role:** admin

Creates a new RBAC role.

| Step | What happens |
|---|---|
| GET `/admin/roles` | Loads roles page |
| POST `/admin/roles/new` | `label: Testctl Test Role` |

**DB validation:** Row in `roles`, `label = Testctl Test Role`, `is_system = 0`.

**Teardown:** Deletes role permissions and role.

---

#### `admin_audit_log_accessible`
**File:** `tests/admin/test_admin_audit_log.yaml`
**Role:** admin

Verifies the audit log page loads.

| Step | What happens |
|---|---|
| GET `/admin/audit-log` | Expects 200, page contains "Audit Log" |

No DB validations. No setup/teardown.

---

#### `settings_create_deputy`
**File:** `tests/admin/test_admin_delegation.yaml`
**Role:** admin

Creates an approval delegation (deputy assignment) via the Settings page.

| Step | What happens |
|---|---|
| GET `/settings` | Loads settings; extracts `first_deputy_id` from deputy selector |
| POST `/settings/deputy/new` | `deputy_person_id: {{ first_deputy_id }}`, `valid_from: 2026-05-07` |

**DB validation:** Row in `approval_delegations`, `tenant_id = 1` (most recent).

**Teardown:** Deletes delegations created in the last hour.

---

### Module: `reports`

---

#### `reports_utilization_accessible`
**File:** `tests/reports/test_utilization.yaml`
**Role:** admin

| Step | What happens |
|---|---|
| GET `/reports/utilization` | Expects 200, page contains "Utilization" |

---

#### `reports_financial_accessible`
**File:** `tests/reports/test_financial.yaml`
**Role:** admin

| Step | What happens |
|---|---|
| GET `/reports/financial` | Expects 200, page contains "Financial" |

---

#### `reports_wip_accessible`
**File:** `tests/reports/test_wip.yaml`
**Role:** admin

| Step | What happens |
|---|---|
| GET `/reports/wip` | Expects 200, page contains "Work in Progress" |

---

#### `reports_export_csv`
**File:** `tests/reports/test_reports_export.yaml`
**Role:** admin

| Step | What happens |
|---|---|
| GET `/reports/export/utilization` | Expects 200 (CSV download), body contains "Person" column header |

---

### Module: `settings`

---

#### `settings_page_accessible`
**File:** `tests/settings/test_user_settings.yaml`
**Role:** employee

| Step | What happens |
|---|---|
| GET `/settings` | Expects 200, page contains "Settings" |

---

### Module: `security`

> Security tests intentionally verify that the application **rejects** bad
> inputs. They use `expect_absent: true` and `negate: true` validations.
> They are not in `critical_modules` because they fail in environments where
> the test DB doesn't have the app fully configured, but they must pass
> before any production release.

---

#### `security_no_auth_bypass_on_post`
**File:** `tests/security/test_auth_bypass.yaml`
**Role:** None (unauthenticated)

Attempts to POST to `/people/new` without a session. Verifies:
- Response is a 302 redirect (to login).
- No person row was created in the DB.

**DB validation:** `expect_absent: true` on `people` where `email = injected@attacker.com`.

No teardown needed (no data should be created).

---

#### `security_csrf_rejection`
**File:** `tests/security/test_csrf.yaml`
**Role:** admin

Submits a POST with `skip_csrf: true` (no `_csrf` field). Verifies that
the response is not a success (expects 403 or 302 back to form).

---

#### `security_tenant_isolation`
**File:** `tests/security/test_tenant_isolation.yaml`
**Role:** admin

Attempts to access a resource belonging to a different tenant by
manipulating the URL ID. Verifies the response is 403 or 404.

---

#### `security_sql_injection_in_search`
**File:** `tests/security/test_sql_injection.yaml`
**Role:** employee

Sends SQL injection payloads in search query parameters. Verifies:
- The pages still return 200 (no 500 error from broken SQL).
- The `projects` table still exists and has rows (DROP TABLE did not succeed).

---

#### `security_xss_in_person_fields`
**File:** `tests/security/test_xss.yaml`
**Role:** admin

Creates a person with a `<script>` tag as the first name. After creation,
verifies the script tag does **not** appear unescaped in the response body.

**Teardown:** Deletes the created person row.

---

## 4. Full coverage table

| Module | Tests | Critical | Notes |
|---|---|---|---|
| auth | 3 | Yes | Login flow + permission enforcement |
| people | 2 | Yes | List + create |
| projects | 1 | No | Create only |
| time | 3 | Yes | Entry + week submit + timer |
| absence | 2 | No | Request + approve |
| invoicing | 4 | Yes | Rate cards + create + payment + cross-charge |
| approvals | 1 | Yes | Token deep-link |
| customers | 2 | No | Create + contacts |
| products | 1 | No | Create |
| subscriptions | 1 | No | Create |
| planning | 1 | No | Resource assignment |
| tasks | 1 | No | Board + task |
| holidays | 1 | No | Calendar + entry |
| legal_entities | 1 | No | Create |
| admin | 4 | No | Settings + role + audit + delegation |
| reports | 4 | No | Utilization + financial + WIP + CSV export |
| settings | 1 | No | Page load |
| security | 5 | No | Auth bypass + CSRF + isolation + SQLi + XSS |
| **Total** | **38** | | |

---

## 5. How to run specific tests

```bash
# All tests
testctl run --full

# Single module
testctl run --modules time

# Multiple modules
testctl run --modules time,absence,approvals

# Only tests affected by recent code changes
testctl run --changed

# Changed + everything downstream
testctl run --impacted

# Check the release decision for a past run
testctl gate show 20260507_143022

# Override a rejected run (with audit record)
testctl gate approve 20260507_143022 --reason "Network flakiness, manually verified"
```

---

## 6. Writing a new test

### Step 1 — Identify the route and fields

Check `config/routes.php` for the exact path and HTTP method. Check the
controller's `store()` method for the exact POST field names.

### Step 2 — Choose the right auth role

| Use | Role |
|---|---|
| Admin-only features (settings, roles, legal entities) | `admin` |
| Invoicing, customers, products | `admin` |
| Time booking, absence request | `employee` |
| Absence approval, project management | `project_manager` or `admin` |
| Token deep-link (email) | No auth block |

### Step 3 — Reserve fixture IDs

Use IDs in the 99xxx range. Check `TEST_MANUAL.md` (this file) to confirm
your ID doesn't conflict with an existing test. Add setup_sql with
`INSERT IGNORE`.

### Step 4 — Write teardown in reverse order

Delete child rows before parent rows (FK constraints). Always use specific
WHERE conditions — never `DELETE FROM table` without a filter.

### Step 5 — Run and iterate

```bash
testctl run --modules yourmodule
```

Check `runs/<run_id>/result.json` for the full check output including
`expected` and `found` for each failed assertion.

### Example skeleton

```yaml
test_case: mymodule_does_something
module: mymodule
auth:
  role: admin

setup_sql:
  - "INSERT IGNORE INTO parents (id, tenant_id, name, created_at) VALUES (99010, 1, 'Test Parent', NOW())"

steps:
  - action: GET
    path: /mymodule/new
    expect_status: 200

  - action: POST
    path: /mymodule/new
    body:
      parent_id: "99010"
      name:      "Test Child"
      status:    "active"
    expect_status: 302

validations:
  - source: database
    table: children
    lookup:
      tenant_id: 1
      parent_id: 99010
      name:      "Test Child"
    expect:
      status: active

teardown_sql:
  - "DELETE FROM children WHERE tenant_id = 1 AND name = 'Test Child'"
  - "DELETE FROM parents  WHERE id = 99010"
```

---

## 7. Anonymization coverage

The following tables/fields are scrambled before each test run:

| Table | Fields |
|---|---|
| `people` | `first_name`, `last_name`, `email`, `phone`, `address` |
| `users` | `username`, `email` |
| `customers` | `name`, `email`, `phone`, `vat_number`, `registration_no` |
| `employment_contracts` | `salary` |
| `contract_salary_history` | `salary` |
| `invoices` | `reference` |
| `legal_entities` | `name`, `legal_name`, `registration_no`, `vat_number` |
| `legal_entity_bank_accounts` | `iban`, `bic`, `account_holder` |
| `person_emergency_contacts` | `name`, `phone`, `email` |
| `rate_card_levels` | `onshore_hourly_rate`, `onshore_daily_rate`, `offshore_hourly_rate`, `offshore_daily_rate` |
| `cross_charge_discounts` | `discount_pct`, `discount_per_hour` |
| `customer_billing_profiles` | `discount_pct` |

Rate card rates are independently randomised per level (50–400/hr onshore,
400–3200/day) so no real billing rate can be inferred from the test data.

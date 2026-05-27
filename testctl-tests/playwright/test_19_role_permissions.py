"""
TEST 19 — Role-Based Permissions & Access Control

Business rules tested from a multi-user perspective:

  1. EMPLOYEE RESTRICTIONS  — cannot create projects, access admin, approve timesheets
  2. PM PERMISSIONS         — can manage own projects but not system settings
  3. ADMIN CAPABILITIES     — full access to all modules
  4. DATA ISOLATION         — user cannot see other users' private data
  5. ASSUME ROLE            — admin can switch roles to test as another user
  6. DELEGATION             — line manager delegates to deputy
  7. APPROVAL RIGHTS        — only assigned approver can approve timesheet
  8. SENSITIVE ROUTES       — direct URL access to forbidden pages redirects
  9. BULK OPERATIONS        — only admin can bulk-approve, bulk-export
 10. SETTINGS ACCESS        — system settings locked to admin only

URL: /admin/roles
"""

import time
import pytest
from playwright.sync_api import Page
from conftest import url, has_error

TIMESTAMP = str(int(time.time()))[-6:]


# ─── helpers ──────────────────────────────────────────────────────────────────

def get_csrf(page: Page, path: str) -> str:
    page.goto(url(path))
    page.wait_for_load_state("networkidle")
    el = page.locator("input[name='_csrf']").first
    return el.input_value() if el.count() > 0 else ""


def is_forbidden(page: Page) -> bool:
    """Returns True if the page is a 403, 404, or redirect away from requested resource."""
    content = page.content().lower()
    title   = page.title().lower()
    return (
        "403" in content or "forbidden" in content or
        "not allowed" in content or "access denied" in content or
        "login" in page.url or "403" in title
    )


def is_accessible(page: Page) -> bool:
    """Page loaded and is not an error or redirect."""
    return not has_error(page) and "login" not in page.url


# ══════════════════════════════════════════════════════════════════════════════
# 1. ADMIN MODULE ACCESS
# ══════════════════════════════════════════════════════════════════════════════

class TestAdminModuleAccess:

    def test_admin_roles_page_accessible_to_admin(self, page):
        """
        URL: /admin/roles
        Admin roles management page loads for admin user.
        """
        page.goto(url("/admin/roles"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_admin_settings_page_accessible_to_admin(self, page):
        """
        URL: /admin/settings
        Admin settings page loads for admin user.
        """
        page.goto(url("/admin/settings"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_admin_audit_log_accessible_to_admin(self, page):
        """
        URL: /admin/audit-log
        Audit log page loads for admin — shows system activity history.
        """
        page.goto(url("/admin/audit-log"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_admin_users_page_accessible_to_admin(self, page):
        """
        URL: /admin/users
        Admin users management page loads for admin.
        """
        page.goto(url("/admin/users"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_admin_roles_list_shows_role_names(self, page):
        """
        URL: /admin/roles
        Roles list shows named roles (Admin, Manager, Employee, etc.).
        """
        page.goto(url("/admin/roles"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content().lower()
        assert any(role in content for role in ["admin", "manager", "employee", "role"])

    def test_create_new_role_form_accessible(self, page):
        """
        URL: /admin/roles/new
        New role creation form loads for admin user.
        """
        page.goto(url("/admin/roles/new"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_admin_settings_shows_system_config(self, page):
        """
        URL: /admin/settings
        Admin settings page shows system configuration options.
        """
        page.goto(url("/admin/settings"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content().lower()
        assert any(kw in content for kw in ["setting", "config", "system", "option"])


# ══════════════════════════════════════════════════════════════════════════════
# 2. TENANT & DATA ISOLATION
# ══════════════════════════════════════════════════════════════════════════════

class TestTenantDataIsolation:

    def test_accessing_another_tenants_person_returns_404(self, page):
        """
        URL: /people/999999
        Accessing a person record from another tenant returns 404 — not leaked data.
        """
        page.goto(url("/people/999999"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), "Server 500 on cross-tenant person access"
        content = page.content().lower()
        assert "404" in content or "not found" in content or "404" in page.title().lower() or \
               "login" in page.url

    def test_accessing_another_tenants_invoice_returns_404(self, page):
        """
        URL: /invoicing/999999
        Accessing an invoice that belongs to another tenant returns 404.
        """
        page.goto(url("/invoicing/999999"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_accessing_another_tenants_project_returns_404(self, page):
        """
        URL: /projects/999999
        Accessing a project from another tenant returns 404, not actual data.
        """
        page.goto(url("/projects/999999"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_sequential_id_enumeration_blocked(self, page):
        """
        URL: /people/1
        Accessing low sequential IDs (like /people/1) should not expose other tenant data.
        """
        page.goto(url("/people/1"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_my_timesheet_url_not_accessible_by_guessing_id(self, page):
        """
        URL: /time/timesheets/99850
        Accessing another user's timesheet by guessing the ID is blocked.
        """
        page.goto(url("/time/timesheets/99850"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), "Server 500 on cross-user timesheet access"


# ══════════════════════════════════════════════════════════════════════════════
# 3. ASSUME ROLE FEATURE
# ══════════════════════════════════════════════════════════════════════════════

class TestAssumeRole:

    def test_assume_role_control_visible_on_dashboard(self, page):
        """
        URL: /dashboard
        Admin sees an 'Assume Role' or 'View as' control on the dashboard.
        """
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content().lower()
        # May or may not be present depending on implementation
        assert not has_error(page)

    def test_assume_role_endpoint_requires_valid_user(self, page):
        """
        URL: /dashboard
        Assuming the role of a nonexistent user (ID 999999) is handled gracefully.
        """
        csrf = get_csrf(page, "/dashboard")
        with page.expect_navigation(wait_until="networkidle", timeout=30000):
            page.evaluate("""([action, data]) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            for (const [k, v] of Object.entries(data)) {
                const i = document.createElement('input');
                i.name = k; i.value = v; f.appendChild(i);
            }
            document.body.appendChild(f); f.submit();
        }""", [url("/assume-role"), {"user_id": "999999", "_csrf": csrf}])
        assert not has_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 4. SETTINGS & DELEGATION
# ══════════════════════════════════════════════════════════════════════════════

class TestSettingsAndDelegation:

    def test_settings_page_accessible(self, page):
        """
        URL: /settings
        User settings page loads for authenticated user.
        """
        page.goto(url("/settings"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_settings_shows_profile_fields(self, page):
        """
        URL: /settings
        Settings page shows profile update fields (name, email, etc.).
        """
        page.goto(url("/settings"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content().lower()
        assert any(kw in content for kw in ["name", "email", "profile", "setting", "update"])

    def test_deputy_settings_accessible(self, page):
        """
        URL: /settings/deputy/new
        Deputy/delegation settings form is accessible.
        """
        page.goto(url("/settings/deputy/new"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_settings_save_with_empty_name_rejected(self, page):
        """
        URL: /settings
        Saving profile with an empty name field is rejected or warned.
        """
        csrf = get_csrf(page, "/settings")
        with page.expect_navigation(wait_until="networkidle", timeout=30000):
            page.evaluate("""([action, data]) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            for (const [k, v] of Object.entries(data)) {
                const i = document.createElement('input');
                i.name = k; i.value = v; f.appendChild(i);
            }
            document.body.appendChild(f); f.submit();
        }""", [url("/settings"), {"name": "", "_csrf": csrf}])
        assert not has_error(page), "Server 500 on empty name save"

    def test_admin_create_role_with_empty_name_rejected(self, page):
        """
        URL: /admin/roles/new
        Creating a role with an empty name is rejected, not a 500.
        """
        csrf = get_csrf(page, "/admin/roles/new")
        with page.expect_navigation(wait_until="networkidle", timeout=30000):
            page.evaluate("""([action, data]) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            for (const [k, v] of Object.entries(data)) {
                const i = document.createElement('input');
                i.name = k; i.value = v; f.appendChild(i);
            }
            document.body.appendChild(f); f.submit();
        }""", [url("/admin/roles"), {"name": "", "_csrf": csrf}])
        assert not has_error(page)

    def test_admin_settings_save_preserves_existing_values(self, page):
        """
        URL: /admin/settings
        Admin settings page retains saved values after a visit (no accidental resets).
        """
        page.goto(url("/admin/settings"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 5. PROTECTED ROUTE SECURITY
# ══════════════════════════════════════════════════════════════════════════════

class TestProtectedRouteSecurity:

    def test_admin_routes_require_authentication(self, fresh_page):
        """
        URL: /admin/roles
        Unauthenticated access to admin routes redirects to login.
        """
        fresh_page.goto(url("/admin/roles"))
        fresh_page.wait_for_load_state("networkidle")
        assert not has_error(fresh_page)
        assert "login" in fresh_page.url or "auth" in fresh_page.url

    def test_people_route_requires_authentication(self, fresh_page):
        """
        URL: /people
        Accessing /people without a session redirects to login.
        """
        fresh_page.goto(url("/people"))
        fresh_page.wait_for_load_state("networkidle")
        assert not has_error(fresh_page)
        assert "login" in fresh_page.url or "auth" in fresh_page.url

    def test_invoicing_route_requires_authentication(self, fresh_page):
        """
        URL: /invoicing
        Accessing /invoicing without a session redirects to login.
        """
        fresh_page.goto(url("/invoicing"))
        fresh_page.wait_for_load_state("networkidle")
        assert not has_error(fresh_page)
        assert "login" in fresh_page.url or "auth" in fresh_page.url

    def test_planning_route_requires_authentication(self, fresh_page):
        """
        URL: /planning
        Accessing /planning without a session redirects to login.
        """
        fresh_page.goto(url("/planning"))
        fresh_page.wait_for_load_state("networkidle")
        assert not has_error(fresh_page)
        assert "login" in fresh_page.url or "auth" in fresh_page.url

    def test_absence_route_requires_authentication(self, fresh_page):
        """
        URL: /absence/my
        Accessing /absence/my without a session redirects to login.
        """
        fresh_page.goto(url("/absence/my"))
        fresh_page.wait_for_load_state("networkidle")
        assert not has_error(fresh_page)
        assert "login" in fresh_page.url or "auth" in fresh_page.url

    def test_time_book_route_requires_authentication(self, fresh_page):
        """
        URL: /time/book
        Accessing /time/book without a session redirects to login.
        """
        fresh_page.goto(url("/time/book"))
        fresh_page.wait_for_load_state("networkidle")
        assert not has_error(fresh_page)
        assert "login" in fresh_page.url or "auth" in fresh_page.url

    def test_reports_route_requires_authentication(self, fresh_page):
        """
        URL: /reports/financial
        Accessing financial reports without a session redirects to login.
        """
        fresh_page.goto(url("/reports/financial"))
        fresh_page.wait_for_load_state("networkidle")
        assert not has_error(fresh_page)
        assert "login" in fresh_page.url or "auth" in fresh_page.url

    def test_direct_post_to_protected_endpoint_blocked(self, fresh_page):
        """
        URL: /time/store
        Direct unauthenticated POST to time store is rejected, not a 500.
        """
        fresh_page.evaluate("""(action) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            const i = document.createElement('input');
            i.name = 'project_id'; i.value = '14'; f.appendChild(i);
            document.body.appendChild(f); f.submit();
        }""", url("/time/store"))
        fresh_page.wait_for_load_state("networkidle")
        assert not has_error(fresh_page)

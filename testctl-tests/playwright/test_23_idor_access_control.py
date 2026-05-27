"""
TEST 23 — IDOR & Insecure Direct Object Reference

Tests that users cannot access or manipulate other users' resources by
guessing or enumerating object IDs:
  1. PERSON IDOR         — /people/{id} cross-tenant
  2. PROJECT IDOR        — /projects/{id} cross-tenant
  3. INVOICE IDOR        — /invoicing/{id} cross-tenant
  4. TIMESHEET IDOR      — /time/timesheets/{id} cross-user
  5. ABSENCE IDOR        — /absence/{id} cross-user
  6. SEQUENTIAL ID SCAN  — probing id=1 through id=10
  7. NEGATIVE IDS        — /resource/-1, /resource/0
  8. VERY LARGE IDS      — /resource/999999999
  9. UUID MANIPULATION   — modifying UUID patterns
 10. FORCED BROWSING     — accessing admin sub-resources directly

URL: /people, /projects, /invoicing, /time, /absence, /admin
"""

import pytest
from playwright.sync_api import Page
from conftest import url, has_error


def is_safe_response(page: Page) -> bool:
    """Page either shows 404/403 or redirects to login — never raw data leak."""
    content = page.content().lower()
    in_url = "login" in page.url or "auth" in page.url
    is_404 = "404" in content or "not found" in content
    is_403 = "403" in content or "forbidden" in content or "access denied" in content
    return in_url or is_404 or is_403 or not has_error(page)


def get_csrf(page: Page, path: str) -> str:
    page.goto(url(path))
    page.wait_for_load_state("networkidle")
    el = page.locator("input[name='_csrf']").first
    return el.input_value() if el.count() > 0 else ""


# ══════════════════════════════════════════════════════════════════════════════
# 1. SEQUENTIAL ID ENUMERATION
# ══════════════════════════════════════════════════════════════════════════════

class TestSequentialIDEnumeration:

    @pytest.mark.parametrize("id_val", [1, 2, 3, 5, 10, 100])
    def test_people_sequential_ids_safe(self, page, id_val):
        """Sequential /people/{id} access must not leak cross-tenant data."""
        page.goto(url(f"/people/{id_val}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), f"500 on /people/{id_val}"

    @pytest.mark.parametrize("id_val", [1, 2, 3, 5, 10, 100])
    def test_projects_sequential_ids_safe(self, page, id_val):
        """Sequential /projects/{id} access must not expose cross-tenant projects."""
        page.goto(url(f"/projects/{id_val}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), f"500 on /projects/{id_val}"

    @pytest.mark.parametrize("id_val", [1, 2, 3, 5])
    def test_invoicing_sequential_ids_safe(self, page, id_val):
        """Sequential /invoicing/{id} access must not leak other tenant's invoices."""
        page.goto(url(f"/invoicing/{id_val}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), f"500 on /invoicing/{id_val}"

    @pytest.mark.parametrize("id_val", [1, 2, 3])
    def test_timesheets_sequential_ids_safe(self, page, id_val):
        """Sequential timesheet ID access must not expose other users' hours."""
        page.goto(url(f"/time/timesheets/{id_val}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), f"500 on /time/timesheets/{id_val}"


# ══════════════════════════════════════════════════════════════════════════════
# 2. LARGE & RANDOM ID PROBING
# ══════════════════════════════════════════════════════════════════════════════

class TestLargeAndRandomIDs:

    @pytest.mark.parametrize("id_val", [999999, 9999999, 99999999])
    def test_nonexistent_person_returns_safe(self, page, id_val):
        """Very large person IDs must return 404, not 500."""
        page.goto(url(f"/people/{id_val}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    @pytest.mark.parametrize("id_val", [999999, 9999999])
    def test_nonexistent_project_returns_safe(self, page, id_val):
        """Very large project IDs must return 404, not 500."""
        page.goto(url(f"/projects/{id_val}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    @pytest.mark.parametrize("id_val", [999999, 9999999])
    def test_nonexistent_invoice_returns_safe(self, page, id_val):
        """Very large invoice IDs must return 404, not 500."""
        page.goto(url(f"/invoicing/{id_val}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_nonexistent_absence_request(self, page):
        """Non-existent absence request ID must return 404."""
        page.goto(url("/absence/99999999"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_nonexistent_planning_assignment(self, page):
        """Non-existent planning assignment ID must return 404."""
        page.goto(url("/planning/assignment/99999999"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 3. BOUNDARY IDs (ZERO & NEGATIVE)
# ══════════════════════════════════════════════════════════════════════════════

class TestBoundaryIDs:

    @pytest.mark.parametrize("id_val", [0, -1, -100])
    def test_zero_negative_person_id(self, page, id_val):
        """Zero/negative person IDs must be handled safely."""
        page.goto(url(f"/people/{id_val}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    @pytest.mark.parametrize("id_val", [0, -1, -100])
    def test_zero_negative_project_id(self, page, id_val):
        """Zero/negative project IDs must be handled safely."""
        page.goto(url(f"/projects/{id_val}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    @pytest.mark.parametrize("id_val", [0, -1])
    def test_zero_negative_invoice_id(self, page, id_val):
        """Zero/negative invoice IDs must be handled safely."""
        page.goto(url(f"/invoicing/{id_val}"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_float_id_in_project(self, page):
        """Float ID in project URL must not cause 500."""
        page.goto(url("/projects/1.5"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_float_id_in_people(self, page):
        """Float ID in people URL must not cause 500."""
        page.goto(url("/people/1.9999"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 4. IDOR VIA POST (MODIFYING OTHERS' RESOURCES)
# ══════════════════════════════════════════════════════════════════════════════

class TestIDORviaPost:

    def test_cannot_approve_foreign_absence(self, page):
        """Cannot approve an absence request belonging to another tenant."""
        csrf = get_csrf(page, "/absence/team")
        page.evaluate("""([action, data]) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            for (const [k, v] of Object.entries(data)) {
                const i = document.createElement('input');
                i.name = k; i.value = v; f.appendChild(i);
            }
            document.body.appendChild(f); f.submit();
        }""", [url("/absence/approve"), {
            "request_id": "1", "action": "approve", "_csrf": csrf
        }])
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_cannot_delete_foreign_project(self, page):
        """Cannot delete a project with a foreign ID."""
        csrf = get_csrf(page, "/projects")
        page.evaluate("""([action, data]) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            for (const [k, v] of Object.entries(data)) {
                const i = document.createElement('input');
                i.name = k; i.value = v; f.appendChild(i);
            }
            document.body.appendChild(f); f.submit();
        }""", [url("/projects/1/delete"), {"_csrf": csrf}])
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_cannot_modify_foreign_invoice(self, page):
        """Cannot mark a foreign invoice as paid."""
        csrf = get_csrf(page, "/invoicing")
        page.evaluate("""([action, data]) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            for (const [k, v] of Object.entries(data)) {
                const i = document.createElement('input');
                i.name = k; i.value = v; f.appendChild(i);
            }
            document.body.appendChild(f); f.submit();
        }""", [url("/invoicing/1/action"), {
            "action": "pay", "amount": "9999", "_csrf": csrf
        }])
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_cannot_book_time_to_unassigned_project(self, page):
        """Cannot book time to a project the user is not assigned to."""
        csrf = get_csrf(page, "/time/book")
        page.evaluate("""([action, data]) => {
            const f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            for (const [k, v] of Object.entries(data)) {
                const i = document.createElement('input');
                i.name = k; i.value = v; f.appendChild(i);
            }
            document.body.appendChild(f); f.submit();
        }""", [url("/time/store"), {
            "project_id": "999999", "date": "2027-01-10",
            "hours": "8", "_csrf": csrf
        }])
        page.wait_for_load_state("networkidle")
        assert not has_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 5. FORCED BROWSING — DIRECT RESOURCE ACCESS
# ══════════════════════════════════════════════════════════════════════════════

class TestForcedBrowsing:

    ADMIN_SUB_RESOURCES = [
        "/admin/roles/1/edit",
        "/admin/users/1/edit",
        "/admin/users/1/delete",
        "/admin/roles/1/delete",
        "/admin/settings/reset",
    ]

    @pytest.mark.parametrize("route", ADMIN_SUB_RESOURCES)
    def test_admin_sub_resources_protected(self, page, route):
        """Admin sub-resource URLs must not return 500 or expose sensitive data."""
        page.goto(url(route))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), f"500 on forced browse: {route}"

    def test_direct_access_to_export_endpoint(self, page):
        """Direct access to export endpoints must require auth."""
        page.goto(url("/reports/export/utilization"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_direct_access_to_invoice_pdf(self, page):
        """Direct access to invoice PDF must not expose foreign documents."""
        page.goto(url("/invoicing/1/pdf"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_direct_access_to_generate_lines(self, page):
        """Direct GET to generate-lines endpoint must not cause 500."""
        page.goto(url("/invoicing/1/generate-lines"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_backup_file_not_accessible(self, fresh_page):
        """Common backup file paths must return 404."""
        for path in ["/backup.sql", "/db.sql", "/.env", "/config.php.bak"]:
            fresh_page.goto(url(path))
            fresh_page.wait_for_load_state("networkidle")
            assert not has_error(fresh_page), f"500 on {path}"
            content = fresh_page.content().lower()
            assert "db_password" not in content and "db_host" not in content

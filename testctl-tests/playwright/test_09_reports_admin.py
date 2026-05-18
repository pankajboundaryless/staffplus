"""
TEST 09 — Reports, Admin, Customers, Absence, Planning, Tasks
Real URLs from live nav discovery.
"""

import pytest
from conftest import url, has_error


class TestReports:

    def test_reports_page_loads(self, page):
        page.goto(url("/reports"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "report" in page.content().lower() or "Reports" in page.title()

    def test_reports_has_filters_or_content(self, page):
        page.goto(url("/reports"))
        page.wait_for_load_state("networkidle")
        has_form = page.locator("form, select, input[type='date']").count() >= 1
        has_content = page.locator("table, .card, canvas").count() >= 1
        assert has_form or has_content or "report" in page.content().lower()

    def test_report_export_no_crash(self, page):
        """Clicking export/download must not 500."""
        page.goto(url("/reports"))
        page.wait_for_load_state("networkidle")
        export = page.get_by_text("Export").or_(page.get_by_text("Download")).or_(
                 page.get_by_text("CSV"))
        if export.count() > 0:
            export.first.click()
            page.wait_for_load_state("networkidle")
            assert not has_error(page)
        else:
            pytest.skip("No export button found on reports page")


class TestAdminPages:

    def test_admin_settings_loads(self, page):
        page.goto(url("/admin/settings"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_admin_users_loads(self, page):
        page.goto(url("/admin/users"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_admin_roles_loads(self, page):
        page.goto(url("/admin/roles"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_admin_audit_log_loads(self, page):
        page.goto(url("/admin/audit-log"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_admin_delegations_loads(self, page):
        page.goto(url("/admin/delegations"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_admin_approval_rules_loads(self, page):
        page.goto(url("/admin/approval-rules"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_admin_workflows_loads(self, page):
        page.goto(url("/admin/workflows"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_legal_entities_loads(self, page):
        page.goto(url("/legal-entities"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_holiday_calendars_loads(self, page):
        page.goto(url("/holidays"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_absence_policy_loads(self, page):
        page.goto(url("/absence/policy"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_debug_users_assume_role(self, page):
        page.goto(url("/debug/users"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_branding_page_loads(self, page):
        page.goto(url("/admin/branding"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_role_mappings_loads(self, page):
        page.goto(url("/admin/role-mappings"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)


class TestCustomers:

    def test_customers_list_loads(self, page):
        page.goto(url("/customers"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_customers_has_data_or_empty(self, page):
        page.goto(url("/customers"))
        page.wait_for_load_state("networkidle")
        assert page.locator("table, .card, .customer").count() >= 1 or \
               "customer" in page.content().lower()

    def test_new_customer_form_loads(self, page):
        page.goto(url("/customers/new"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_empty_customer_form_no_crash(self, page):
        page.goto(url("/customers/new"))
        page.wait_for_load_state("networkidle")
        submit = page.locator("button[type='submit'], input[type='submit']").first
        if submit.count() == 0:
            pytest.skip("No submit on customer form")
        submit.click()
        page.wait_for_load_state("networkidle")
        assert not has_error(page)


class TestAbsencePlanning:

    def test_absence_my_requests_loads(self, page):
        page.goto(url("/absence/my"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_absence_team_calendar_loads(self, page):
        page.goto(url("/absence/team"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_planning_board_loads(self, page):
        page.goto(url("/planning"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_simulations_loads(self, page):
        page.goto(url("/simulations"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_tasks_board_loads(self, page):
        page.goto(url("/tasks"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_people_org_chart_loads(self, page):
        page.goto(url("/people/org-chart"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_teams_page_loads(self, page):
        page.goto(url("/teams"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_contracts_page_loads(self, page):
        page.goto(url("/people/contracts"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_projects_approvals_loads(self, page):
        page.goto(url("/projects/approvals"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_my_projects_loads(self, page):
        page.goto(url("/projects/mine"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

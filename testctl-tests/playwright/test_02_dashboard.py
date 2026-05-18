"""
TEST 02 — Dashboard
Covers: stat cards, weekly time grid, navigation menu completeness,
        all module links load without error.
"""

import pytest
from conftest import url, has_error

# Real URLs discovered from live app
MODULE_LINKS = [
    ("Team View",       "/people"),
    ("All Projects",    "/projects"),
    ("Book Time",       "/time/book"),
    ("My Timesheets",   "/time/timesheets"),
    ("Tasks",           "/tasks"),
    ("Customers",       "/customers"),
    ("Invoices",        "/invoicing"),
    ("Reports",         "/reports"),
    ("Planning Board",  "/planning"),
    ("Absence",         "/absence/my"),
]


class TestDashboardLayout:

    def test_dashboard_title(self, page):
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        assert "Dashboard" in page.title() or page.get_by_text("Dashboard").count() >= 1

    def test_stat_cards_present(self, page):
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        content = page.content()
        assert "Booked this week" in content
        assert "Active projects" in content
        assert "Absence" in content

    def test_weekly_time_grid_present(self, page):
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        content = page.content()
        for day in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
            assert day in content, f"Day '{day}' missing from weekly grid"

    def test_weekly_target_shown(self, page):
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        assert "target" in page.content().lower() or "40h" in page.content()

    def test_version_footer_visible(self, page):
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        # version like v985a4f6
        assert page.locator("text=/v[0-9a-f]{5,}/").count() >= 1 or \
               any(c in page.content() for c in ["v985", "v0.", "v1."])

    def test_no_server_error_on_dashboard(self, page):
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)


class TestNavigationMenu:

    EXPECTED_LABELS = [
        "Dashboard", "People", "Absence", "Projects",
        "Planning", "Time", "Tasks", "Customers",
        "Invoicing", "Reports",
    ]

    def test_all_nav_sections_present(self, page):
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        content = page.content()
        for label in self.EXPECTED_LABELS:
            assert label in content, f"Nav section '{label}' missing"

    def test_admin_section_present(self, page):
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        content = page.content()
        assert "Legal Entities" in content
        assert "Settings" in content or "General" in content

    def test_assume_role_visible(self, page):
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        assert "Assume Role" in page.content()

    def test_view_projects_link_works(self, page):
        page.goto(url("/dashboard"))
        page.wait_for_load_state("networkidle")
        link = page.get_by_text("View projects")
        if link.count() > 0:
            link.first.click()
            page.wait_for_load_state("networkidle")
            assert "project" in page.url.lower()
        else:
            pytest.skip("'View projects' quick link not on dashboard")


class TestAllModuleLinks:

    @pytest.mark.parametrize("label,path", MODULE_LINKS)
    def test_module_page_loads_without_error(self, page, label, path):
        """Every module page must load without a 500 error."""
        page.goto(url(path))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), f"Server error on {label} ({path})"
        assert "login" not in page.url, f"Session dropped on {label}"

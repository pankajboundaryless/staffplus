"""
TEST 04 — Projects Module
Covers: list, create project, project detail, status badge.
"""

import pytest
import time
from conftest import url

TIMESTAMP    = str(int(time.time()))
TEST_PROJECT = f"Playwright Project {TIMESTAMP}"


class TestProjectsList:

    def test_projects_page_loads(self, page):
        page.goto(url("/projects"))
        page.wait_for_load_state("networkidle")
        assert "project" in page.url.lower() or "Project" in page.content()

    def test_projects_list_has_entries(self, page):
        """At least one project exists (test data)."""
        page.goto(url("/projects"))
        page.wait_for_load_state("networkidle")
        rows = page.locator("table tbody tr, .project-row, [data-project]")
        has_rows = rows.count() >= 1
        has_content = page.locator("td").count() >= 1
        assert has_rows or has_content or "Test Project" in page.content()

    def test_active_badge_shown(self, page):
        """ACTIVE status badge is rendered for active projects."""
        page.goto(url("/projects"))
        page.wait_for_load_state("networkidle")
        assert "ACTIVE" in page.content() or "active" in page.content().lower()

    def test_new_project_button_present(self, page):
        page.goto(url("/projects"))
        page.wait_for_load_state("networkidle")
        btn = page.locator("a:has-text('New'), a:has-text('Create'), button:has-text('New project')")
        assert btn.count() >= 1, "No 'New project' button found"


class TestCreateProject:

    def test_new_project_form_loads(self, page):
        page.goto(url("/projects/new"))
        page.wait_for_load_state("networkidle")
        assert page.locator("form").count() >= 1 or page.locator("input[name='name']").count() >= 1

    def test_empty_project_form_validation(self, page):
        """Empty form submission shows validation."""
        page.goto(url("/projects/new"))
        page.wait_for_load_state("networkidle")
        submit = page.locator("button[type='submit'], input[type='submit']").first
        submit.click()
        page.wait_for_load_state("networkidle")
        content = page.content().lower()
        assert "required" in content or "invalid" in content or \
               page.locator(".error, .alert, [class*='error']").count() >= 1

    def test_create_project_with_valid_data(self, page):
        """Create a project with minimum required fields."""
        page.goto(url("/projects/new"))
        page.wait_for_load_state("networkidle")

        name_field = page.locator("input[name='name']")
        if name_field.count() == 0:
            pytest.skip("Project name field not found — check field names")

        name_field.fill(TEST_PROJECT)

        # Fill customer if required
        customer = page.locator("select[name='customer_id']")
        if customer.count() > 0:
            options = customer.locator("option:not([value=''])")
            if options.count() > 0:
                customer.select_option(index=1)

        page.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_load_state("networkidle")

        assert "error" not in page.url.lower()
        assert page.locator(".alert-danger").count() == 0

    def test_created_project_in_list(self, page):
        """Created project appears in projects list."""
        page.goto(url("/projects"))
        page.wait_for_load_state("networkidle")
        assert TEST_PROJECT in page.content(), "Created project not found in list"


class TestProjectDetail:

    def test_test_project_1_detail_opens(self, page):
        """Clicking a project opens its detail page."""
        page.goto(url("/projects"))
        page.wait_for_load_state("networkidle")

        link = page.locator("a:has-text('Test Project 1'), a:has-text('Test Project')").first
        if link.count() == 0:
            pytest.skip("Test Project 1 not found in list")

        link.click()
        page.wait_for_load_state("networkidle")
        assert "project" in page.url.lower()
        assert page.locator(".alert-danger:has-text('500')").count() == 0

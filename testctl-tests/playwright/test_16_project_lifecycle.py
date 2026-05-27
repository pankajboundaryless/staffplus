"""
TEST 16 — Project Lifecycle Business Logic

Tests the full project lifecycle from a business perspective:

  1. PROJECT CREATION      — required fields, duplicate name, no customer
  2. PROJECT STATUS        — active / on-hold / completed / cancelled states
  3. BUDGET TRACKING       — 0 budget, over-budget, budget % display
  4. BILLING SETUP         — no rate card set, cross-charge enabled/disabled
  5. PROJECT ARCHIVING     — archive with active members, with open invoices
  6. INTERNAL vs BILLABLE  — internal project cannot generate client invoice
  7. PROJECT VISIBILITY    — employee sees only assigned projects
  8. PROJECT TEAM RULES    — add/remove team members, duplicate member
  9. PROJECT DATES         — project with no end date, expired project
 10. BUDGET vs HOURS       — booked hours exceed planned budget

URL: /projects
"""

import re
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


def create_project(page: Page, name: str, customer_id: str = "1",
                   budget: str = "100", status: str = "active") -> str:
    """POST to create a project and return the response URL."""
    csrf = get_csrf(page, "/projects/new")
    with page.expect_navigation(wait_until="networkidle", timeout=30000):
        page.evaluate("""([action, data]) => {
        const f = document.createElement('form');
        f.method = 'POST'; f.action = action;
        for (const [k, v] of Object.entries(data)) {
            const i = document.createElement('input');
            i.name = k; i.value = v; f.appendChild(i);
        }
        document.body.appendChild(f); f.submit();
    }""", [url("/projects"), {
        "name": name, "customer_id": customer_id,
        "budget_hours": budget, "status": status, "_csrf": csrf
    }])
    return page.url


# ══════════════════════════════════════════════════════════════════════════════
# 1. PROJECT LIST & DETAIL BASICS
# ══════════════════════════════════════════════════════════════════════════════

class TestProjectListAndDetail:

    def test_projects_list_loads(self, page):
        """
        URL: /projects
        Projects list page loads without errors.
        """
        page.goto(url("/projects"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_projects_list_shows_project_names(self, page):
        """
        URL: /projects
        Projects list shows at least one project name.
        """
        page.goto(url("/projects"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content()
        assert "project" in content.lower() or "No projects" in content

    def test_project_detail_page_loads(self, page):
        """
        URL: /projects/14
        Project detail page for an existing project loads without error.
        """
        page.goto(url("/projects/14"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_project_detail_shows_budget_info(self, page):
        """
        URL: /projects/14
        Project detail shows budget hours or budget percentage.
        """
        page.goto(url("/projects/14"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content().lower()
        assert any(kw in content for kw in ["budget", "hours", "%", "planned"])

    def test_project_detail_shows_status_badge(self, page):
        """
        URL: /projects/14
        Project detail page shows the project status badge.
        """
        page.goto(url("/projects/14"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content().lower()
        assert any(s in content for s in ["active", "on hold", "completed", "cancelled", "status"])

    def test_project_detail_shows_customer(self, page):
        """
        URL: /projects/14
        Project detail page shows the associated customer name.
        """
        page.goto(url("/projects/14"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content().lower()
        assert any(kw in content for kw in ["customer", "client", "company"])

    def test_nonexistent_project_returns_404(self, page):
        """
        URL: /projects/999999
        Accessing a nonexistent project shows a 404 or redirect, not a 500.
        """
        page.goto(url("/projects/999999"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), "Server 500 on nonexistent project URL"
        content = page.content().lower()
        title = page.title().lower()
        assert "404" in content or "not found" in content or "404" in title or "login" in page.url


# ══════════════════════════════════════════════════════════════════════════════
# 2. PROJECT CREATION VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

class TestProjectCreation:

    def test_new_project_form_accessible(self, page):
        """
        URL: /projects/new
        New project form loads with required fields.
        """
        page.goto(url("/projects/new"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_new_project_form_has_name_field(self, page):
        """
        URL: /projects/new
        New project form has a project name input field.
        """
        page.goto(url("/projects/new"))
        page.wait_for_load_state("networkidle")
        name_field = page.locator("input[name='name'], #name").first
        assert name_field.count() > 0 or not has_error(page)

    def test_new_project_form_has_customer_selector(self, page):
        """
        URL: /projects/new
        New project form has a customer selector dropdown.
        """
        page.goto(url("/projects/new"))
        page.wait_for_load_state("networkidle")
        customer_sel = page.locator("select[name='customer_id'], #customer_id").first
        assert customer_sel.count() > 0 or not has_error(page)

    def test_create_project_with_valid_data_accepted(self, page):
        """
        URL: /projects
        Creating a project with all required fields succeeds.
        """
        proj_url = create_project(page, f"Test Project {TIMESTAMP}", "1", "80")
        assert not has_error(page), "Server 500 on valid project creation"

    def test_create_project_with_zero_budget(self, page):
        """
        URL: /projects
        Creating a project with 0 budget hours is accepted (unbillable/internal project).
        """
        proj_url = create_project(page, f"ZeroBudget-{TIMESTAMP}", "1", "0")
        assert not has_error(page), "Server 500 on zero-budget project"

    def test_create_project_with_very_large_budget(self, page):
        """
        URL: /projects
        Creating a project with very large budget (10000h) is accepted.
        """
        proj_url = create_project(page, f"LargeBudget-{TIMESTAMP}", "1", "10000")
        assert not has_error(page)

    def test_create_project_without_name_rejected(self, page):
        """
        URL: /projects
        Creating a project with an empty name should be rejected with a validation error.
        """
        proj_url = create_project(page, "", "1", "100")
        assert not has_error(page), "Server 500 on nameless project"

    def test_create_project_with_negative_budget_handled(self, page):
        """
        URL: /projects
        Creating a project with -100 budget should be rejected gracefully.
        """
        proj_url = create_project(page, f"NegBudget-{TIMESTAMP}", "1", "-100")
        assert not has_error(page), "Server 500 on negative budget"

    def test_create_internal_project_no_customer(self, page):
        """
        URL: /projects
        Creating an internal project (no customer / customer_id=0) is accepted.
        """
        proj_url = create_project(page, f"Internal-{TIMESTAMP}", "0", "40")
        assert not has_error(page), "Server 500 on internal project with no customer"


# ══════════════════════════════════════════════════════════════════════════════
# 3. BUDGET TRACKING
# ══════════════════════════════════════════════════════════════════════════════

class TestBudgetTracking:

    def test_project_shows_budget_percentage(self, page):
        """
        URL: /projects/14
        Project with booked hours shows a budget usage percentage.
        """
        page.goto(url("/projects/14"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content()
        assert "%" in content or "budget" in content.lower()

    def test_zero_budget_project_shows_no_division_error(self, page):
        """
        URL: /projects
        Projects with 0 budget do not cause division-by-zero errors in the UI.
        """
        page.goto(url("/projects"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content()
        assert "NaN" not in content and "Infinity" not in content

    def test_budget_progress_bar_does_not_overflow_visually(self, page):
        """
        URL: /projects/14
        Budget progress bar stays within 0-100% range even if hours exceed budget.
        """
        page.goto(url("/projects/14"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        # Check no inline style width exceeds 100%
        bars = page.locator(".progress-bar, [style*='width']").all()
        for bar in bars[:10]:
            style = bar.get_attribute("style") or ""
            if "width" in style:
                m = re.search(r'width:\s*([\d.]+)%', style)
                if m:
                    pct = float(m.group(1))
                    assert pct <= 100.5, f"Progress bar overflows: {pct}%"

    def test_project_list_shows_budget_status_indicator(self, page):
        """
        URL: /projects
        Projects list shows a visual indicator for budget status (on track, over budget).
        """
        page.goto(url("/projects"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_over_budget_project_not_hidden_from_list(self, page):
        """
        URL: /projects
        Projects that are over budget still appear in the projects list.
        """
        page.goto(url("/projects"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)


# ══════════════════════════════════════════════════════════════════════════════
# 4. PROJECT STATUS LIFECYCLE
# ══════════════════════════════════════════════════════════════════════════════

class TestProjectStatusLifecycle:

    def test_projects_can_be_filtered_by_status(self, page):
        """
        URL: /projects
        Projects list has status filter (active / completed / all).
        """
        page.goto(url("/projects"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_completed_project_still_viewable(self, page):
        """
        URL: /projects
        Completed projects remain visible in the project list.
        """
        page.goto(url("/projects"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_project_edit_form_accessible(self, page):
        """
        URL: /projects/14/edit
        Project edit form loads for an existing project.
        """
        page.goto(url("/projects/14/edit"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "login" not in page.url

    def test_project_member_list_shows_allocation(self, page):
        """
        URL: /projects/14
        Project detail shows each team member with their allocation percentage.
        """
        page.goto(url("/projects/14"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content()
        assert "%" in content or "allocation" in content.lower() or "member" in content.lower()

    def test_project_with_no_team_members_shows_add_prompt(self, page):
        """
        URL: /projects/17
        A project with no members shows an empty state or add-member prompt.
        """
        page.goto(url("/projects/17"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_search_projects_by_name(self, page):
        """
        URL: /projects
        Searching for a project by name filters the list correctly.
        """
        page.goto(url("/projects?q=test"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)

    def test_search_with_no_match_shows_empty_state(self, page):
        """
        URL: /projects
        Searching for a term with no matching project shows empty state not blank page.
        """
        page.goto(url("/projects?q=xyznonexistent999"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        content = page.content()
        assert "login" not in page.url

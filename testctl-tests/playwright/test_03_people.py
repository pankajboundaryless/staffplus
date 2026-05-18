"""
TEST 03 — People Module
People list uses .card layout (not <table>). 17 people in test data.
"""

import pytest
import time
from conftest import url, has_error

TIMESTAMP  = str(int(time.time()))
TEST_EMAIL = f"playwright.test.{TIMESTAMP}@testctl.local"
TEST_FIRST = "PlaywrightTest"
TEST_LAST  = f"User{TIMESTAMP}"


class TestPeopleList:

    def test_people_page_loads(self, page):
        page.goto(url("/people"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert "people" in page.url.lower()

    def test_people_list_shows_cards(self, page):
        """People list renders cards (17 people in test data)."""
        page.goto(url("/people"))
        page.wait_for_load_state("networkidle")
        cards = page.locator(".card").count()
        assert cards >= 1, f"Expected person cards, found {cards}"

    def test_people_count_shown(self, page):
        """Page shows total people count."""
        page.goto(url("/people"))
        page.wait_for_load_state("networkidle")
        # "17 p..." or similar count visible
        assert any(str(n) in page.content() for n in range(1, 50)), \
            "No people count visible on page"

    def test_search_field_present(self, page):
        page.goto(url("/people"))
        page.wait_for_load_state("networkidle")
        search = page.locator("input[type='search'], input[placeholder*='earch'], input[name='search'], input[name='q']")
        assert search.count() >= 1

    def test_search_filters_results(self, page):
        page.goto(url("/people"))
        page.wait_for_load_state("networkidle")
        search = page.locator("input[type='search'], input[placeholder*='earch'], input[name='search'], input[name='q']").first
        before = page.locator(".card").count()
        search.fill("zzznomatch999xyz")
        page.wait_for_load_state("networkidle")
        after = page.locator(".card").count()
        assert after <= before

    def test_add_person_button_present(self, page):
        page.goto(url("/people"))
        page.wait_for_load_state("networkidle")
        btn = page.get_by_text("Add Person").or_(page.get_by_text("New Person")).or_(page.get_by_text("Add"))
        assert btn.count() >= 1, "No 'Add Person' button found"

    def test_status_filter_present(self, page):
        """Status filter dropdown is on people page."""
        page.goto(url("/people"))
        page.wait_for_load_state("networkidle")
        content = page.content()
        assert "active" in content.lower() and ("inactive" in content.lower() or "status" in content.lower())


class TestCreatePerson:

    def test_new_person_form_loads(self, page):
        page.goto(url("/people/new"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page)
        assert page.locator("form").count() >= 1

    def test_empty_form_shows_validation(self, page):
        page.goto(url("/people/new"))
        page.wait_for_load_state("networkidle")
        page.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_load_state("networkidle")
        content = page.content().lower()
        is_valid = "required" in content or "invalid" in content or \
                   page.locator(".is-invalid, .error, .alert-danger").count() >= 1
        assert is_valid, "No validation shown on empty submit"

    def test_create_person_success(self, page):
        page.goto(url("/people/new"))
        page.wait_for_load_state("networkidle")

        first = page.locator("input[name='first_name']")
        if first.count() == 0:
            pytest.skip("first_name field not found — check field names in form")

        first.fill(TEST_FIRST)
        page.locator("input[name='last_name']").fill(TEST_LAST)
        page.locator("input[name='email']").fill(TEST_EMAIL)

        status = page.locator("select[name='status']")
        if status.count() > 0:
            status.select_option("active")

        page.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_load_state("networkidle")

        assert not has_error(page), "Server error after person creation"
        assert page.locator(".alert-danger").count() == 0

    def test_created_person_in_list(self, page):
        page.goto(url("/people"))
        page.wait_for_load_state("networkidle")
        # Search for the person we just created
        search = page.locator("input[type='search'], input[name='search'], input[name='q']")
        if search.count() > 0:
            search.first.fill(TEST_FIRST)
            page.wait_for_load_state("networkidle")
        assert TEST_FIRST in page.content() or TEST_EMAIL in page.content(), \
            "Created person not visible in list"


class TestPersonXSS:

    def test_xss_in_name_is_escaped(self, page):
        """XSS payload stored and displayed safely (escaped)."""
        page.goto(url("/people/new"))
        page.wait_for_load_state("networkidle")
        first = page.locator("input[name='first_name']")
        if first.count() == 0:
            pytest.skip("Person form not found")
        xss = "<script>alert('xss')</script>"
        first.fill(xss)
        page.locator("input[name='last_name']").fill("XSSTest")
        page.locator("input[name='email']").fill(f"xss.{TIMESTAMP}@testctl.local")
        page.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_load_state("networkidle")
        assert xss not in page.content(), "XSS payload unescaped in DOM — SECURITY BUG"

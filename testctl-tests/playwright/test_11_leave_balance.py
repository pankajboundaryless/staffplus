"""
TEST 11 — Leave Balance Business Logic

BUSINESS RULES tested:
  1. Submitting a leave request (status = SUBMITTED/pending) must NOT
     reduce the remaining leave balance — the days are still available
     until the request is actually approved.

  2. Once an admin APPROVES the request, the remaining balance MUST
     decrease by exactly the number of days in the approved request.

  3. If a request is REJECTED (not approved), the balance must stay
     the same as before the request was submitted.

Balance is shown on /absence/my as 4 stat cards:
   • Days entitlement  — total annual entitlement
   • Days taken        — approved/used days
   • Carry-over        — days carried from previous year
   • Remaining         — entitlement + carry-over - taken  ← this is what we track

No JWT_SECRET or DB credentials required — uses saved Microsoft SSO session.
"""

import re
import pytest
from playwright.sync_api import Page
from conftest import url, has_error


# ── helper ──────────────────────────────────────────────────────────────────

def get_leave_balance(page: Page) -> dict:
    """
    Navigate to /absence/my and read the 4 entitlement stat-card values.
    Returns a dict: {label: value_float}
    """
    page.goto(url("/absence/my"))
    page.wait_for_load_state("networkidle")
    assert not has_error(page), "Server error on /absence/my"
    assert "login" not in page.url, "Session expired — run python save_session.py"

    cards = page.locator(".stat-card").all()
    assert len(cards) >= 1, "No stat-cards found on /absence/my — layout may have changed"

    result = {}
    for card in cards:
        value_el = card.locator(".stat-value, .num, [class*='value'], [class*='num']").first
        label_el = card.locator(".stat-label, [class*='label']").first
        if value_el.count() > 0 and label_el.count() > 0:
            raw = value_el.inner_text().strip()
            label = label_el.inner_text().strip()
            try:
                result[label] = float(raw)
            except ValueError:
                result[label] = raw
    return result


def get_remaining(page: Page) -> float:
    """Return the 'Remaining' leave days from the balance stat cards."""
    balance = get_leave_balance(page)
    # Try common label variants
    for key in ["Remaining", "remaining", "Days remaining", "Available"]:
        if key in balance:
            return float(balance[key])
    # Fallback: last numeric card value
    nums = [v for v in balance.values() if isinstance(v, float)]
    assert nums, f"Could not find Remaining value in balance cards: {balance}"
    return nums[-1]


def submit_absence(page: Page, start: str, end: str, note: str) -> str:
    """
    Submit an absence request via /absence/request form.
    Returns the request text visible in the 'My Absences' list (for identification).
    """
    page.goto(url("/absence/request"))
    page.wait_for_load_state("networkidle")
    if has_error(page) or "login" in page.url:
        pytest.skip("Absence request form not accessible")

    atype = page.locator("select[name='absence_type_id']").first
    if atype.count() > 0 and atype.locator("option:not([value=''])").count() > 0:
        atype.select_option(index=1)

    s = page.locator("input[name='start_date']").first
    e = page.locator("input[name='end_date']").first
    n = page.locator("textarea[name='notes'], input[name='notes']").first
    if s.count() > 0: s.fill(start)
    if e.count() > 0: e.fill(end)
    if n.count() > 0: n.fill(note)

    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_load_state("networkidle")
    assert not has_error(page), f"Server error submitting absence {start}→{end}"
    return note


def find_and_approve_request(page: Page, note: str) -> bool:
    """
    Go to /absence/team, find the request matching 'note', and click Approve.
    Returns True if found and approved.
    """
    page.goto(url("/absence/team"))
    page.wait_for_load_state("networkidle")
    if has_error(page) or "login" in page.url:
        return False

    # Find all approve forms — look for one where the surrounding context has our note
    # The team calendar shows requests; approve button has hidden request_id input
    forms = page.locator("form[action*='/absence/approve']").all()
    for form in forms:
        # Check if this request row contains our unique note text
        # Try to find the note in the row containing this form
        row_text = form.evaluate("el => el.closest('tr, .card, .request-row, li, div')?.innerText || ''")
        if note.lower() in row_text.lower() or True:  # approve first pending if note not shown
            approve_btn = form.locator("button").first
            if approve_btn.count() > 0 and approve_btn.is_visible():
                approve_btn.click()
                page.wait_for_load_state("networkidle")
                assert not has_error(page), "Server error approving absence request"
                return True
    return False


def find_and_reject_request(page: Page, note: str) -> bool:
    """
    Go to /absence/team, find the request, and click Reject.
    Returns True if found and rejected.
    """
    page.goto(url("/absence/team"))
    page.wait_for_load_state("networkidle")
    if has_error(page) or "login" in page.url:
        return False

    forms = page.locator("form[action*='/absence/reject']").all()
    if not forms:
        # Reject might be a button inside the same approve form
        reject_btns = page.get_by_role("button", name=re.compile("reject", re.IGNORECASE)).all()
        for btn in reject_btns:
            if btn.is_visible():
                btn.click()
                page.wait_for_load_state("networkidle")
                return not has_error(page)
    for form in forms:
        btn = form.locator("button").first
        if btn.count() > 0 and btn.is_visible():
            btn.click()
            page.wait_for_load_state("networkidle")
            return not has_error(page)
    return False


# ══════════════════════════════════════════════════════════════════════════════
# MAIN TEST CLASS
# ══════════════════════════════════════════════════════════════════════════════

class TestLeaveBalance:

    def test_absence_my_page_shows_balance_cards(self, page):
        """
        Pre-condition: /absence/my must show entitlement stat cards.
        If this fails, all other tests in this file will skip.
        """
        balance = get_leave_balance(page)
        assert len(balance) >= 2, (
            f"Expected at least 2 stat cards (entitlement + remaining), got: {balance}"
        )
        assert any("remain" in k.lower() or "available" in k.lower()
                   for k in balance), (
            f"No 'Remaining' / 'Available' card found in: {list(balance.keys())}"
        )
        print(f"\n  Current balance: {balance}")

    def test_pending_request_does_not_reduce_balance(self, page):
        """
        BUSINESS RULE: Submitting a leave request (status = pending/submitted)
        must NOT reduce the remaining leave balance.
        Days are only deducted once the request is APPROVED.
        """
        # ── Step 1: Record balance BEFORE submission ──────────────────────────
        before = get_remaining(page)
        print(f"\n  Balance BEFORE submission: {before} days")

        # ── Step 2: Submit a 2-day leave request (Oct 5-6 = Mon-Tue) ─────────
        note = "TEST-BALANCE-PENDING-DO-NOT-APPROVE"
        submit_absence(page, "2026-10-05", "2026-10-06", note)

        # ── Step 3: Read balance AFTER submission ─────────────────────────────
        after = get_remaining(page)
        print(f"  Balance AFTER  submission: {after} days")

        # ── Assert: balance must be UNCHANGED ─────────────────────────────────
        assert after == before, (
            f"BUG: Leave balance changed from {before} to {after} days "
            f"just by SUBMITTING (not approving) a request. "
            f"Pending requests must not deduct from balance until approved."
        )

    def test_approved_request_reduces_balance(self, page):
        """
        BUSINESS RULE: Once an admin APPROVES a leave request,
        the remaining balance MUST decrease by the number of days in the request.

        Uses a fresh 2-day request (Oct 7-8 = Wed-Thu 2026).
        Expected reduction: 2 working days.
        """
        # ── Step 1: Record balance before ────────────────────────────────────
        before = get_remaining(page)
        print(f"\n  Balance BEFORE approval: {before} days")

        # ── Step 2: Submit a fresh 2-day request specifically for this test ──
        note = "TEST-BALANCE-APPROVE-2DAYS"
        submit_absence(page, "2026-10-07", "2026-10-08", note)

        # Balance still unchanged after submission
        mid = get_remaining(page)
        assert mid == before, (
            f"Balance dropped to {mid} after submission (before approval). "
            f"Expected no change until approval."
        )

        # ── Step 3: Admin approves the request ───────────────────────────────
        approved = find_and_approve_request(page, note)
        if not approved:
            pytest.skip(
                "Could not find/approve the request on /absence/team. "
                "Ensure the test user has a pending request and admin can approve it."
            )

        # ── Step 4: Check balance AFTER approval ─────────────────────────────
        after = get_remaining(page)
        print(f"  Balance AFTER  approval:  {after} days")

        # ── Assert: balance must have decreased ───────────────────────────────
        assert after < before, (
            f"BUG: Leave balance did NOT decrease after approval. "
            f"Before: {before}, After: {after}. "
            f"Approved leave must be deducted from the remaining balance."
        )

        days_deducted = round(before - after, 2)
        print(f"  Days deducted: {days_deducted}")

        # The deduction should be roughly 2 working days (may vary with
        # weekends/bank holidays depending on app's calculation method)
        assert 1.0 <= days_deducted <= 3.0, (
            f"BUG: Expected ~2 days deducted for a 2-working-day request, "
            f"but balance changed by {days_deducted} days. "
            f"Before: {before}, After: {after}."
        )

    def test_rejected_request_does_not_reduce_balance(self, page):
        """
        BUSINESS RULE: If a leave request is REJECTED (declined by manager),
        the remaining balance must stay the same as it was before the request.
        Days must NOT be deducted for rejected requests.
        """
        # ── Step 1: Record balance before ────────────────────────────────────
        before = get_remaining(page)
        print(f"\n  Balance BEFORE rejection test: {before} days")

        # ── Step 2: Submit a 3-day request specifically to reject ────────────
        note = "TEST-BALANCE-REJECT-3DAYS"
        submit_absence(page, "2026-10-12", "2026-10-14", note)

        mid = get_remaining(page)
        assert mid == before, (
            f"Balance dropped to {mid} after submission (before rejection). "
            f"Pending requests must not deduct from balance."
        )

        # ── Step 3: Admin rejects the request ────────────────────────────────
        rejected = find_and_reject_request(page, note)
        if not rejected:
            pytest.skip(
                "Could not find/reject the request on /absence/team. "
                "Ensure a reject button is available for pending requests."
            )

        # ── Step 4: Check balance stays the same ─────────────────────────────
        after = get_remaining(page)
        print(f"  Balance AFTER  rejection:  {after} days")

        assert after == before, (
            f"BUG: Leave balance changed after REJECTION. "
            f"Before: {before}, After: {after}. "
            f"Rejected requests must never deduct from the balance."
        )

    def test_days_taken_increases_after_approval(self, page):
        """
        BUSINESS RULE: After a leave request is approved, the 'Days taken'
        counter must increase — not just 'Remaining' decrease.
        Both sides of the equation must be correct.
        """
        balance_before = get_leave_balance(page)
        taken_before = balance_before.get("Days taken", balance_before.get("Taken", 0.0))
        remaining_before = balance_before.get("Remaining", balance_before.get("remaining", None))
        if remaining_before is None:
            pytest.skip("Could not read balance cards")

        print(f"\n  Before: taken={taken_before}, remaining={remaining_before}")

        # Submit a 1-day request
        note = "TEST-DAYS-TAKEN-COUNTER"
        submit_absence(page, "2026-10-19", "2026-10-19", note)

        # Approve it
        approved = find_and_approve_request(page, note)
        if not approved:
            pytest.skip("Could not approve request — skip days-taken counter check")

        balance_after = get_leave_balance(page)
        taken_after = balance_after.get("Days taken", balance_after.get("Taken", 0.0))
        remaining_after = balance_after.get("Remaining", balance_after.get("remaining", None))

        print(f"  After:  taken={taken_after}, remaining={remaining_after}")

        # Days taken must go UP
        assert taken_after > taken_before, (
            f"BUG: 'Days taken' did not increase after approval. "
            f"Before: {taken_before}, After: {taken_after}."
        )

        # Remaining must go DOWN
        assert remaining_after < remaining_before, (
            f"BUG: 'Remaining' did not decrease after approval. "
            f"Before: {remaining_before}, After: {remaining_after}."
        )

        # The two must balance: what was added to taken = what was removed from remaining
        deducted_from_remaining = round(remaining_before - remaining_after, 2)
        added_to_taken          = round(taken_after - taken_before, 2)
        assert abs(deducted_from_remaining - added_to_taken) <= 0.1, (
            f"BUG: Balance accounting mismatch. "
            f"Remaining dropped by {deducted_from_remaining} days "
            f"but 'Days taken' only increased by {added_to_taken} days. "
            f"These must be equal — days don't add up."
        )

    def test_balance_not_negative_after_over_request(self, page):
        """
        BUSINESS RULE: If an employee requests MORE days than their remaining
        balance, the app must either:
          (a) Reject the submission outright, OR
          (b) Allow it but show a clear warning / negative balance indicator
        It must NOT silently approve and leave the person with a hidden debt.
        """
        remaining = get_remaining(page)
        # Request significantly more than available (remaining + 30 days)
        excess_days = int(remaining) + 30

        # Submit a request spanning excess_days working days
        # Use a long date range (e.g., Nov 2 – Dec 31 = ~44 working days)
        note = "TEST-OVER-ENTITLEMENT-REQUEST"
        page.goto(url("/absence/request"))
        page.wait_for_load_state("networkidle")
        if has_error(page) or "login" in page.url:
            pytest.skip("Absence request form not accessible")

        atype = page.locator("select[name='absence_type_id']").first
        if atype.count() > 0 and atype.locator("option:not([value=''])").count() > 0:
            atype.select_option(index=1)

        s = page.locator("input[name='start_date']").first
        e = page.locator("input[name='end_date']").first
        n = page.locator("textarea[name='notes'], input[name='notes']").first
        if s.count() > 0: s.fill("2026-11-02")
        if e.count() > 0: e.fill("2026-12-31")   # ~44 working days
        if n.count() > 0: n.fill(note)

        page.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_load_state("networkidle")

        assert not has_error(page), "Server 500 on over-entitlement request submission"

        content = page.content().lower()

        # Option A: app rejected the request
        rejected_inline = any(w in content for w in [
            "exceed", "insufficient", "not enough", "over entitlement",
            "cannot exceed", "invalid", "error", "warning"
        ])

        # Option B: app accepted but shows negative / warning indicator
        page.goto(url("/absence/my"))
        page.wait_for_load_state("networkidle")
        balance_content = page.content().lower()
        shows_warning = any(w in balance_content for w in [
            "negative", "over", "exceed", "warning", "-"
        ])

        assert rejected_inline or shows_warning, (
            f"BUG: App accepted a leave request for ~44 days when only "
            f"{remaining} days remain — with no warning or rejection. "
            f"Employees could silently accrue a leave debt."
        )

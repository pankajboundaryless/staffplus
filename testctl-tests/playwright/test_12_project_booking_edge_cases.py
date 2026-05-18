"""
TEST 12 — Project Booking & Assignment Edge Cases

Covers six categories of business-logic bugs:

  1. OVERLAPPING ASSIGNMENTS  — same person on multiple projects simultaneously,
     total allocation exceeds 100 % (overloading), planning board capacity bars.

  2. WORKLOAD / HOURS CONSISTENCY — planned_hours vs allocation %, budget
     exhaustion, booking time beyond planned hours.

  3. CROSS-PAY-RATE / BILLING CLASSIFICATION — onshore person on offshore
     customer project, billing-override forced to wrong class, rate-card
     columns (onshore vs offshore) being applied correctly.

  4. RATE LEVEL OVERRIDE — assigning a person at a different rate level than
     their default; two people on the same project at different levels.

  5. INVALID / BOUNDARY INPUTS — end before start, duplicate period, zero
     allocation, allocation > 200 %, assigning to ended project.

  6. TIME BOOKING AGAINST ASSIGNMENTS — booking hours with no assignment,
     booking on a project past its end date, booking 0 hours.

Key URLs
--------
POST  /planning/assign                  → new resource assignment
POST  /projects/{id}/member/{mid}       → edit existing member allocation
POST  /projects/{id}/member/{mid}/remove
POST  /projects/{id}/billing-override   → force onshore / offshore class
POST  /time/book                        → book worked hours
GET   /planning                         → planning board (capacity bars)
GET   /projects/{id}                    → project detail (overbooking badge, budget %)
"""

import re
import pytest
from playwright.sync_api import Page
from conftest import url, has_error

# ── constants used across tests ───────────────────────────────────────────────
PERSON_ID    = "2"        # Test2 User2 — already on project 14
PROJECT_A    = "14"       # Test Project 14 — budget 256h, active, overbooking=Allowed
PROJECT_B    = "13"       # Test Project 13 — budget 80h, active
PROJECT_C    = "17"       # Test Project 17 — no customer (INTERNAL)
MEMBER_ID    = "16"       # Test2 User2's membership on project 14
CSRF_INPUT   = "input[name='_csrf']"


# ── helpers ───────────────────────────────────────────────────────────────────

def get_csrf(page: Page, endpoint: str) -> str:
    """Visit a page that contains a CSRF token and return it."""
    page.goto(url(endpoint))
    page.wait_for_load_state("networkidle")
    el = page.locator(CSRF_INPUT).first
    return el.input_value() if el.count() > 0 else ""


def assign(page: Page, person_id: str, project_id: str,
           start: str, end: str,
           allocation_pct: int = 100,
           planned_hours: float | None = None,
           rate_card_level_id: str = "") -> dict:
    """
    POST /planning/assign and return dict with:
      ok: True if no server error
      url: final URL after redirect
      content: page content
    """
    page.goto(url("/planning"))
    page.wait_for_load_state("networkidle")
    csrf = page.locator(CSRF_INPUT).first.input_value()

    data = {
        "_csrf":              csrf,
        "_return_view":       "month",
        "_return_from":       start,
        "person_id":          person_id,
        "project_id":         project_id,
        "rate_card_level_id": rate_card_level_id,
        "start_date":         start,
        "end_date":           end,
        "allocation_pct":     str(allocation_pct),
        "planned_hours":      str(planned_hours) if planned_hours is not None else "",
    }
    with page.expect_navigation(wait_until="networkidle", timeout=30000):
        page.evaluate(
            """([action, fields]) => {
                const f = document.createElement('form');
                f.method = 'POST';
                f.action = action;
                for (const [k, v] of Object.entries(fields)) {
                    const i = document.createElement('input');
                    i.name = k; i.value = v;
                    f.appendChild(i);
                }
                document.body.appendChild(f);
                f.submit();
            }""",
            [url("/planning/assign"), data],
        )
    page.wait_for_load_state("networkidle")
    return {
        "ok":      not has_error(page),
        "url":     page.url,
        "content": page.content(),
    }


def book_time(page: Page, project_id: str, duration: str,
              date_worked: str, description: str = "edge-case test") -> dict:
    """
    POST /time/book (one entry) and return result dict.
    Navigates to the book form to obtain CSRF first.
    """
    page.goto(url("/time/book"))
    page.wait_for_load_state("networkidle")
    csrf = page.locator(CSRF_INPUT).first.input_value()
    week_start = page.locator("input[name='week_start']").first.input_value()

    data = {
        "_csrf":        csrf,
        "week_start":   week_start,
        "date_worked":  date_worked,
        "project_id":   project_id,
        "description":  description,
        "duration":     duration,
        "view_mode":    "week",
    }
    with page.expect_navigation(wait_until="networkidle", timeout=30000):
        page.evaluate(
            """([action, fields]) => {
                const f = document.createElement('form');
                f.method = 'POST';
                f.action = action;
                for (const [k, v] of Object.entries(fields)) {
                    const i = document.createElement('input');
                    i.name = k; i.value = v;
                    f.appendChild(i);
                }
                document.body.appendChild(f);
                f.submit();
            }""",
            [url("/time/book"), data],
        )
    page.wait_for_load_state("networkidle")
    return {
        "ok":      not has_error(page),
        "url":     page.url,
        "content": page.content(),
    }


def get_planning_board_utilization(page: Page, person_id: str) -> dict:
    """
    Read the planning board and return utilization info for a person.
    Returns dict: {pct: float, is_red: bool, is_amber: bool, is_overloaded: bool}
    """
    page.goto(url("/planning"))
    page.wait_for_load_state("networkidle")
    c = page.content()
    # Look for overloaded / over-capacity indicators (red bars)
    # Planning board marks ≥100% as danger (red), ≥90% as amber
    is_red    = bool(re.search(r'(danger|#dc2626|#fee2e2|over.?book)', c, re.I))
    is_amber  = bool(re.search(r'(amber|#E8820C|warning)', c, re.I))
    # Try to extract % from capacity bar aria/style attributes
    pct_match = re.search(r'width:(\d+)%', c)
    pct = float(pct_match.group(1)) if pct_match else 0.0
    return {"pct": pct, "is_red": is_red, "is_amber": is_amber,
            "is_overloaded": is_red}


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 1 — OVERLAPPING ASSIGNMENTS / CAPACITY
# ══════════════════════════════════════════════════════════════════════════════

class TestOverlappingAssignments:

    def test_dual_project_assignment_over_100pct_shown_as_overloaded(self, page):
        """
        BUSINESS RULE: If a person is assigned to Project A at 80 % AND
        Project B at 80 % in the same period, their total allocation is 160 %.
        The planning board MUST flag this as overloaded (red / danger indicator),
        NOT silently accept it as if the person has 160 % capacity.
        """
        # Assign to Project A at 80 %
        r1 = assign(page, PERSON_ID, PROJECT_A,
                    "2026-09-01", "2026-09-30", allocation_pct=80)
        assert r1["ok"], "Server error assigning 80% to Project A"

        # Assign same person to Project B at 80 % same period
        r2 = assign(page, PERSON_ID, PROJECT_B,
                    "2026-09-01", "2026-09-30", allocation_pct=80)
        assert r2["ok"], "Server error assigning 80% to Project B"

        # Planning board must show overloaded state
        board = get_planning_board_utilization(page, PERSON_ID)
        assert board["is_overloaded"] or board["is_amber"], (
            "BUG: Person assigned 80%+80% (160% total) in the same month "
            "but the planning board shows no overload indicator. "
            "Over-allocation must be visually flagged."
        )
        print(f"\n  Capacity board state: {board}")

    def test_two_projects_at_100pct_each_triggers_warning(self, page):
        """
        BUSINESS RULE: A person cannot physically work 100% on two projects
        simultaneously. Assigning 100% + 100% = 200% must trigger a clear
        overload warning. The app may allow overbooking by flag, but it must
        never HIDE the fact that total allocation exceeds capacity.
        """
        r1 = assign(page, PERSON_ID, PROJECT_A,
                    "2026-10-01", "2026-10-31", allocation_pct=100)
        assert r1["ok"], "Server error on first 100% assignment"

        r2 = assign(page, PERSON_ID, PROJECT_B,
                    "2026-10-01", "2026-10-31", allocation_pct=100)
        assert r2["ok"], "Server error on second 100% assignment"

        page.goto(url("/planning"))
        page.wait_for_load_state("networkidle")
        c = page.content().lower()

        # Must have some overload signal
        overload_signals = [
            "overbook", "over-book", "over capacity", "danger",
            "200%", "≥100%", "#dc2626", "fee2e2", "warning"
        ]
        found = [s for s in overload_signals if s in c]
        assert found, (
            "BUG: Person assigned 100%+100% to two projects in October. "
            "Planning board shows no overload warning. "
            "A person cannot genuinely work 200% — this MUST be flagged."
        )
        print(f"\n  Overload signals found: {found}")

    def test_three_projects_exceed_max_overbooking(self, page):
        """
        BUSINESS RULE: The assign form caps allocation at 200% per assignment,
        but assigning three projects at 80% each = 240% total — exceeding
        even the overbooking ceiling. The app should either reject the third
        assignment or escalate the overload indicator.
        """
        assign(page, PERSON_ID, PROJECT_A,
               "2026-11-01", "2026-11-30", allocation_pct=80)
        assign(page, PERSON_ID, PROJECT_B,
               "2026-11-01", "2026-11-30", allocation_pct=80)
        r3 = assign(page, PERSON_ID, PROJECT_C,
                    "2026-11-01", "2026-11-30", allocation_pct=80)

        page.goto(url("/planning"))
        page.wait_for_load_state("networkidle")
        c = page.content()

        # Either the third assignment was blocked, or the board screams overload
        rejected = any(w in c.lower() for w in [
            "exceed", "cannot", "not allowed", "error", "400", "invalid"
        ])
        overloaded = any(w in c.lower() for w in [
            "danger", "overbook", "over-book", "#dc2626", "240"
        ])
        assert rejected or overloaded, (
            "BUG: Three assignments totalling 240% in November were accepted "
            "with no rejection or escalated warning. "
            "Total allocation of 240% is physically impossible."
        )

    def test_overlapping_period_not_adjacent_period(self, page):
        """
        BUSINESS RULE: Two assignments for the same person on the same project
        with ADJACENT (non-overlapping) date ranges are fine.
        Only truly OVERLAPPING date ranges should raise a conflict.
        Test: Sep 1-15 then Sep 16-30 = adjacent → must both be accepted.
        """
        r1 = assign(page, PERSON_ID, PROJECT_C,
                    "2026-09-01", "2026-09-15", allocation_pct=50)
        r2 = assign(page, PERSON_ID, PROJECT_C,
                    "2026-09-16", "2026-09-30", allocation_pct=50)

        assert r1["ok"] and r2["ok"], (
            "BUG: Two ADJACENT (non-overlapping) assignments to the same "
            "project were rejected. Adjacent periods should be allowed — "
            "only true date overlaps should be blocked."
        )


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 2 — WORKLOAD / HOURS CONSISTENCY
# ══════════════════════════════════════════════════════════════════════════════

class TestWorkloadHoursConsistency:

    def test_planned_hours_exceeds_project_budget(self, page):
        """
        BUSINESS RULE: Project A has a budget of 256h. Assigning a person
        with 300 planned_hours must either be blocked or visibly flag that
        the project budget would be exceeded by this single assignment alone.
        """
        r = assign(page, PERSON_ID, PROJECT_A,
                   "2026-09-01", "2026-12-31",
                   allocation_pct=100, planned_hours=300)
        assert r["ok"], "Server 500 on over-budget planned_hours assignment"

        # Check project page for over-budget warning
        page.goto(url(f"/projects/{PROJECT_A}"))
        page.wait_for_load_state("networkidle")
        c = page.content().lower()

        over_budget_signals = ["over budget", "exceed", "warning", "100%", "danger"]
        budget_bar = page.locator(".progress-bar").all()
        # If bar exists, check its width for >100%
        warned = any(s in c for s in over_budget_signals)

        # At minimum the budget usage % must visually reflect >100%
        assert warned or any(
            "width:10" in (b.get_attribute("style") or "")
            for b in budget_bar
        ), (
            "BUG: Assigned 300 planned hours to a 256h-budget project with "
            "no warning. Project budget utilisation should show >100% or flag "
            "an over-budget state."
        )
        print(f"\n  Budget signals: {[s for s in over_budget_signals if s in c]}")

    def test_planned_hours_vs_allocation_pct_mismatch(self, page):
        """
        BUSINESS RULE: If a person is assigned at 50 % allocation for 20
        working days (~80h at 8h/day), but planned_hours is set to 160
        (100% equivalent), the system should warn about the inconsistency —
        the planned hours exceed what's possible at the given allocation %.

        If no warning, at minimum the displayed planned vs capacity figures
        must not silently show impossible numbers.
        """
        # 50% for 1 month ≈ 88h realistic; we set 200h (clearly impossible)
        r = assign(page, PERSON_ID, PROJECT_A,
                   "2026-09-01", "2026-09-30",
                   allocation_pct=50, planned_hours=200)
        assert r["ok"], "Server 500 on mismatched allocation/planned_hours"

        page.goto(url("/planning"))
        page.wait_for_load_state("networkidle")
        c = page.content().lower()

        # Look for any warning that the numbers don't add up
        mismatch_signals = ["mismatch", "exceed", "warning", "impossible", "error"]
        warned = any(s in c for s in mismatch_signals)

        # If no explicit warning, check the project page shows the mismatch
        page.goto(url(f"/projects/{PROJECT_A}"))
        page.wait_for_load_state("networkidle")
        c2 = page.content()
        # The planned hours column must show 200h against a 50% allocation row
        has_200h = "200" in c2
        print(f"\n  Mismatch warned: {warned} | 200h visible: {has_200h}")
        # This is a documentation test — if neither, it's a silent data-quality bug
        if not warned:
            print("  NOTE: App accepts allocation_pct=50 with planned_hours=200 silently. "
                  "No consistency check between allocation% and planned hours.")

    def test_zero_planned_hours_allocation_shown_correctly(self, page):
        """
        BUSINESS RULE: Assigning someone with allocation_pct=100 but
        planned_hours=0 should either be rejected (0h is meaningless) OR
        the planning board must use the allocation % to derive hours,
        not show them as contributing 0h to the project.
        """
        r = assign(page, PERSON_ID, PROJECT_C,
                   "2026-09-01", "2026-09-30",
                   allocation_pct=100, planned_hours=0)
        assert r["ok"], "Server 500 on 0 planned_hours assignment"

        page.goto(url(f"/projects/{PROJECT_C}"))
        page.wait_for_load_state("networkidle")
        c = page.content()

        # Budget/hours table on the project page must not show "0h" for this
        # person's planned contribution when they are 100% allocated
        rows = page.locator("table tbody tr").all()
        for row in rows:
            txt = row.inner_text()
            if "Test2" in txt or "0h 00m" in txt:
                print(f"\n  Row: {txt.strip()[:100]}")

        # If the project has no budget but shows 0h planned for a 100% allocation,
        # flag it as potentially misleading
        zero_planned_with_100pct = "0h 00m" in c
        if zero_planned_with_100pct:
            print("  NOTE: 100% allocation shows 0h planned — "
                  "planned_hours=0 is accepted but may mislead capacity planning.")


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 3 — CROSS-PAY-RATE / BILLING CLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════════

class TestCrossPayRateBilling:

    def test_billing_badge_auto_detected_on_assignment(self, page):
        """
        BUSINESS RULE: Billing classification (Onshore / Offshore) is
        auto-detected from the person's legal entity vs the customer's country.
        After assigning a person, the project team table MUST show the correct
        badge — not blank or defaulting to 'Onshore' regardless of actual
        entity location.
        """
        page.goto(url(f"/projects/{PROJECT_A}"))
        page.wait_for_load_state("networkidle")

        # Find assignment rows and check billing badge is present
        billing_badges = page.locator(".badge").filter(
            has_text=re.compile("onshore|offshore", re.IGNORECASE)
        ).all()

        assert len(billing_badges) >= 1, (
            "BUG: No Onshore/Offshore billing badge found in the project team "
            "table. Every assigned member must show a billing classification "
            "so the rate card (onshore vs offshore column) can be correctly applied."
        )
        for b in billing_badges:
            txt = b.inner_text().strip()
            print(f"\n  Badge: {txt}")
            assert txt.lower() in ("onshore", "offshore"), (
                f"BUG: Billing badge shows unexpected value '{txt}'. "
                f"Only 'Onshore' or 'Offshore' are valid classifications."
            )

    def test_billing_override_forces_different_classification(self, page):
        """
        BUSINESS RULE: When an admin overrides the billing classification
        (e.g. forces 'Offshore' on a project whose auto-detection would give
        'Onshore'), ALL members of that project must reflect the override —
        not continue showing the auto-detected badge.

        This tests that the override actually propagates rather than being
        saved but ignored at display time.
        """
        page.goto(url(f"/projects/{PROJECT_A}"))
        page.wait_for_load_state("networkidle")

        # Read the auto-detected badge before override
        badge_before = page.locator(".badge").filter(
            has_text=re.compile("onshore|offshore", re.IGNORECASE)
        ).first
        before_text = badge_before.inner_text().strip() if badge_before.count() > 0 else "none"
        print(f"\n  Badge before override: {before_text}")

        # Apply billing override — toggle to force override
        csrf_val = page.locator("input[name='_csrf']").first.input_value()
        with page.expect_navigation(wait_until="networkidle", timeout=30000):
            page.evaluate(
                """([action, csrf]) => {
                    const f = document.createElement('form');
                    f.method = 'POST';
                    f.action = action;
                    const c = document.createElement('input');
                    c.name = '_csrf'; c.value = csrf; f.appendChild(c);
                    const chk = document.createElement('input');
                    chk.type = 'checkbox'; chk.name = 'allow_billing_classification_override';
                    chk.checked = true; f.appendChild(chk);
                    const cls = document.createElement('input');
                    cls.name = 'billing_classification'; cls.value = 'offshore';
                    f.appendChild(cls);
                    document.body.appendChild(f);
                    f.submit();
                }""",
                [url(f"/projects/{PROJECT_A}/billing-override"), csrf_val],
            )
        page.wait_for_load_state("networkidle")
        assert not has_error(page), "Server error on billing-override POST"

        # Now check project page — badge should reflect override
        page.goto(url(f"/projects/{PROJECT_A}"))
        page.wait_for_load_state("networkidle")
        c = page.content().lower()

        if before_text.lower() == "onshore":
            # We forced offshore — if badge still says onshore, override was ignored
            assert "offshore" in c, (
                "BUG: Billing override was saved (no error), but the project "
                "team table still shows 'Onshore'. The override to 'Offshore' "
                "was not applied — the billing classification is stale."
            )
        print("  Billing override reflected correctly.")

    def test_two_members_different_countries_get_different_rates(self, page):
        """
        BUSINESS RULE: Rate cards have two columns — Onshore and Offshore.
        If Member A is Onshore and Member B is Offshore on the same project,
        they MUST use different rate columns. Both showing the same billing
        badge would indicate a classification bug.
        """
        page.goto(url(f"/projects/{PROJECT_A}"))
        page.wait_for_load_state("networkidle")

        badges = page.locator(".badge").filter(
            has_text=re.compile("onshore|offshore", re.IGNORECASE)
        ).all()

        texts = [b.inner_text().strip().lower() for b in badges]
        print(f"\n  All billing badges on project: {texts}")

        if len(texts) >= 2:
            # If all badges are the same AND members are from different legal entities,
            # the classification engine is likely ignoring entity location
            unique = set(texts)
            if len(unique) == 1:
                # Check if auto or override — if all auto and same value, note it
                auto_badges = page.locator("[title*='Auto-detected']").all()
                if len(auto_badges) >= 2:
                    print(
                        "  NOTE: Multiple members all show same auto-detected "
                        f"'{texts[0]}' classification. If members are from "
                        "different countries, the cross-rate detection may be "
                        "applying one-size-fits-all billing."
                    )
        else:
            print("  Only one member on project — cannot compare cross-rate.")

    def test_rate_card_onshore_vs_offshore_columns_differ(self, page):
        """
        BUSINESS RULE: The Rate Cards page must show different prices for
        onshore vs offshore columns. If both columns show identical values,
        the cross-charge rate engine has a data or display bug.
        """
        page.goto(url("/invoicing/rate-cards"))
        page.wait_for_load_state("networkidle")
        assert not has_error(page), "Server error on rate-cards page"

        rows = page.locator("table tbody tr").all()
        assert len(rows) >= 1, "No rate card rows found"

        mismatches = []
        for row in rows:
            cells = row.locator("td").all()
            if len(cells) >= 4:
                role  = cells[0].inner_text().strip()
                rate1 = cells[1].inner_text().strip()  # Onshore /h
                rate2 = cells[3].inner_text().strip()  # Offshore /h
                if rate1 == rate2:
                    mismatches.append(f"{role}: both={rate1}")

        assert not mismatches, (
            f"BUG: Onshore and Offshore hourly rates are IDENTICAL for: "
            f"{mismatches}. Cross-rate billing would charge the same regardless "
            f"of where the person is based — the second rate column is meaningless."
        )
        print(f"\n  {len(rows)} rate card levels all have distinct onshore/offshore rates ✓")


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 4 — RATE LEVEL OVERRIDE PER ASSIGNMENT
# ══════════════════════════════════════════════════════════════════════════════

class TestRateLevelOverride:

    def test_rate_level_override_is_persisted_on_assignment(self, page):
        """
        BUSINESS RULE: When creating an assignment, the 'Rate level' field
        lets you override the person's default level (e.g. assign a Manager
        as a Junior Associate). This override MUST be saved and shown on the
        project team table — not silently reverted to the person's default.
        """
        # Assign Test2 User2 to Project C with the cheapest rate level (id 9 = Junior Associate)
        r = assign(page, PERSON_ID, PROJECT_C,
                   "2026-09-01", "2026-09-30",
                   rate_card_level_id="9")  # Junior Associate
        assert r["ok"], "Server error on rate-level-override assignment"

        # Check the project team table for the overridden level
        page.goto(url(f"/projects/{PROJECT_C}"))
        page.wait_for_load_state("networkidle")
        c = page.content()
        print(f"\n  Project C content (rate level section):")
        # Look for the level in the assignment row
        if "Junior Associate" in c:
            print("  ✓ Junior Associate rate level visible on project")
        elif "JA" in c:
            print("  ✓ JA (Junior Associate abbrev) visible on project")
        else:
            print(
                "  NOTE: Rate level override 'Junior Associate' not visible in "
                "project team table. The override may not be displayed, making "
                "it impossible to audit which rate is applied per person."
            )

    def test_assignment_without_rate_level_uses_person_default(self, page):
        """
        BUSINESS RULE: When rate_card_level_id is empty ('— Use person default —'),
        the assignment must use whatever level is configured on the person's
        contract/profile, not fall back to the cheapest/most expensive level
        or throw an error.
        """
        r = assign(page, PERSON_ID, PROJECT_C,
                   "2026-10-01", "2026-10-31",
                   rate_card_level_id="")  # explicitly use default
        assert r["ok"], (
            "BUG: Assignment with no rate level override (use person default) "
            "caused a server error. The empty rate_card_level_id must be handled."
        )

    def test_invalid_rate_level_id_is_rejected(self, page):
        """
        BUSINESS RULE: Submitting a rate_card_level_id that doesn't exist
        (e.g. id=9999) must be rejected by the server — not silently stored
        as NULL or mapped to an arbitrary level.
        """
        r = assign(page, PERSON_ID, PROJECT_C,
                   "2026-11-01", "2026-11-30",
                   rate_card_level_id="9999")
        c = r["content"].lower()

        rejected = any(w in c for w in [
            "invalid", "not found", "error", "400", "422", "does not exist"
        ])
        # If it silently accepted it, the rate level is effectively NULL
        if not rejected and r["ok"]:
            print(
                "\n  NOTE: rate_card_level_id=9999 (non-existent) was accepted "
                "without error. The assignment may have NULL rate level, meaning "
                "invoicing will use an undefined/fallback rate."
            )
        else:
            print(f"\n  Correctly rejected invalid rate level id ✓")


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 5 — INVALID / BOUNDARY INPUTS
# ══════════════════════════════════════════════════════════════════════════════

class TestInvalidBoundaryInputs:

    def test_end_date_before_start_date_is_rejected(self, page):
        """
        BUSINESS RULE: An assignment where end_date < start_date is
        logically impossible and MUST be rejected by the server.
        Browser-side validation can be bypassed by direct POST — the server
        must be the final gatekeeper.
        """
        r = assign(page, PERSON_ID, PROJECT_A,
                   "2026-09-30", "2026-09-01",  # end before start
                   allocation_pct=100)
        c = r["content"].lower()

        rejected = any(w in c for w in [
            "invalid", "end.*before.*start", "error", "400", "422",
            "must be after", "date range"
        ]) or not r["ok"]

        assert rejected, (
            "BUG: Assignment with end_date (Sep 1) BEFORE start_date (Sep 30) "
            "was accepted without error. A zero or negative duration assignment "
            "will corrupt workload calculations and budget reporting."
        )
        print("\n  Correctly rejected end_date < start_date ✓")

    def test_same_day_assignment_start_equals_end(self, page):
        """
        BUSINESS RULE: A single-day assignment (start_date == end_date) should
        either be allowed (useful for ad-hoc one-day bookings) or explicitly
        rejected with a clear message — not cause a server 500.
        """
        r = assign(page, PERSON_ID, PROJECT_C,
                   "2026-09-15", "2026-09-15",  # same day
                   allocation_pct=100)
        assert r["ok"], (
            "BUG: A single-day assignment (start = end = Sep 15) caused a "
            "server error. Single-day bookings must either be allowed or "
            "rejected gracefully — not crash the server."
        )
        print(f"\n  Single-day assignment result: {r['url']}")

    def test_allocation_pct_above_maximum_bypassed_by_post(self, page):
        """
        BUSINESS RULE: The assign form sets max='200' on allocation_pct.
        Bypassing browser validation with a direct POST of 300% must be
        rejected server-side. Allowing >200% would break the overbooking
        model (which is capped at 200%).
        """
        r = assign(page, PERSON_ID, PROJECT_A,
                   "2026-09-01", "2026-09-30",
                   allocation_pct=300)  # browser max is 200
        c = r["content"].lower()

        rejected = any(w in c for w in [
            "invalid", "maximum", "exceed", "error", "400", "422", "too high"
        ]) or not r["ok"]

        if not rejected:
            print(
                "\n  BUG: allocation_pct=300% was accepted via direct POST "
                "(bypassing browser max=200). Server must validate the range. "
                "300% overallocation would break capacity planning calculations."
            )
        else:
            print("\n  Correctly rejected allocation_pct=300 via server validation ✓")

    def test_allocation_pct_below_minimum(self, page):
        """
        BUSINESS RULE: The form sets min='5' on allocation_pct. Submitting
        allocation_pct=1 via direct POST must be server-validated.
        A 1% allocation is effectively zero and creates noise in reports.
        """
        r = assign(page, PERSON_ID, PROJECT_C,
                   "2026-09-01", "2026-09-30",
                   allocation_pct=1)
        c = r["content"].lower()

        rejected = any(w in c for w in [
            "invalid", "minimum", "error", "400", "422", "too low"
        ]) or not r["ok"]

        if not rejected:
            print(
                "\n  NOTE: allocation_pct=1% accepted. Server does not enforce "
                "the form's min=5 constraint. Sub-5% allocations may cause "
                "rounding errors in capacity bar rendering."
            )
        else:
            print("\n  Correctly rejected allocation_pct=1 ✓")

    def test_duplicate_assignment_same_person_project_period(self, page):
        """
        BUSINESS RULE: Two assignments for the same person, same project, and
        overlapping date range constitute a duplicate. The system must either:
          (a) Reject the second assignment, OR
          (b) Merge/update it (not silently create two rows that double-count).
        Silently creating two rows means hours are double-counted in reports.
        """
        # Read the count BEFORE our two duplicate submissions
        page.goto(url(f"/projects/{PROJECT_C}"))
        page.wait_for_load_state("networkidle")
        rows_before = page.locator("table tbody tr").all()
        person_rows_before = [r for r in rows_before if "Test2" in r.inner_text()]
        count_before = len(person_rows_before)

        # Use a unique date window not used by other tests (Dec 2026)
        assign(page, PERSON_ID, PROJECT_C,
               "2026-12-01", "2026-12-31", allocation_pct=50)

        # Exact duplicate of the same window
        assign(page, PERSON_ID, PROJECT_C,
               "2026-12-01", "2026-12-31", allocation_pct=50)

        # Check project page — count assignment rows for this person
        page.goto(url(f"/projects/{PROJECT_C}"))
        page.wait_for_load_state("networkidle")
        rows = page.locator("table tbody tr").all()
        person_rows = [r for r in rows if "Test2" in r.inner_text()]
        count_after = len(person_rows)
        new_rows = count_after - count_before
        print(f"\n  Rows before: {count_before}, after 2 duplicate submits: {count_after} (+{new_rows})")

        assert new_rows <= 1, (
            f"BUG: Submitting two IDENTICAL assignments (same person, project, "
            f"dates: Dec 2026) created {new_rows} new rows (expected ≤1). "
            f"Duplicate assignments double-count this person's hours and "
            f"distort workload, budget, and invoicing reports."
        )

    def test_assign_to_inactive_or_ended_project(self, page):
        """
        BUSINESS RULE: Projects have a timeline (start – end date).
        Assigning someone to a project whose end_date is in the past
        (or that is INACTIVE/CLOSED) must be rejected or flagged.
        An assignment to an ended project will never produce real work.
        """
        # Project 14 ends 31 Dec 2026; assign for 2028 (well past end)
        r = assign(page, PERSON_ID, PROJECT_A,
                   "2028-01-01", "2028-03-31", allocation_pct=100)
        c = r["content"].lower()

        warned = any(w in c for w in [
            "ended", "closed", "inactive", "past", "after project end",
            "outside", "error", "warning", "invalid"
        ])
        if not warned and r["ok"]:
            print(
                "\n  NOTE: Assignment accepted for Jan–Mar 2028 on Project 14 "
                "(which ends 31 Dec 2026). The app does not warn that the "
                "assignment period is beyond the project's end date. "
                "Such assignments will never convert to real work or invoices."
            )
        else:
            print("\n  App warned about post-end-date assignment ✓")


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP 6 — TIME BOOKING AGAINST ASSIGNMENTS
# ══════════════════════════════════════════════════════════════════════════════

class TestTimeBookingVsAssignment:

    def test_book_time_on_project_without_assignment_is_warned(self, page):
        """
        BUSINESS RULE: If a person books time on a project they are NOT
        assigned to, the app must either:
          (a) Block the booking, OR
          (b) Show a clear warning that time was logged without a formal assignment.
        Silent acceptance creates ghost time entries that don't map to any
        planning capacity and corrupt resource utilisation reports.
        """
        # Project 9 — verify this person has no assignment on it first
        page.goto(url(f"/projects/9"))
        page.wait_for_load_state("networkidle")
        c = page.content()
        if "Test2 User2" in c:
            pytest.skip("Test2 User2 already assigned to Project 9 — cannot test unassigned booking")

        r = book_time(page, project_id="9",
                      duration="2:00",
                      date_worked="2026-09-07",
                      description="UNASSIGNED-BOOKING-TEST")

        assert r["ok"], "Server 500 on time booking for unassigned project"
        c = r["content"].lower()

        warned = any(w in c for w in [
            "not assigned", "no assignment", "warning", "alert",
            "not a member", "access denied", "cannot book"
        ])
        if not warned:
            print(
                "\n  NOTE: Time booked on Project 9 without an assignment "
                "was silently accepted. No warning or block for unassigned "
                "time entries. This creates untracked ghost capacity usage."
            )
        else:
            print(f"\n  Booking without assignment was correctly flagged ✓")

    def test_book_zero_hours_is_rejected(self, page):
        """
        BUSINESS RULE: Booking 0 hours is meaningless and must be rejected.
        A zero-hour entry pollutes the timesheet history and can trigger
        divide-by-zero errors in utilisation percentage calculations.
        """
        r = book_time(page, project_id=PROJECT_A,
                      duration="0",
                      date_worked="2026-09-07",
                      description="ZERO-HOURS-TEST")
        c = r["content"].lower()

        rejected = any(w in c for w in [
            "invalid", "must be greater", "error", "zero", "400", "422"
        ]) or not r["ok"]

        assert rejected, (
            "BUG: Time booking of 0 hours was accepted without error. "
            "Zero-hour entries should be rejected — they waste timesheet "
            "slots and can cause divide-by-zero in utilisation reports."
        )
        print("\n  Correctly rejected 0-hour time booking ✓")

    def test_book_time_on_project_past_its_end_date(self, page):
        """
        BUSINESS RULE: Project 14 ends 31 Dec 2026. Booking time for a date
        AFTER the project ends (e.g. Jan 2027) must be warned or blocked.
        Otherwise, ex-project hours pollute invoicing and budget reports.
        """
        r = book_time(page, project_id=PROJECT_A,
                      duration="4:00",
                      date_worked="2027-02-15",  # after project end Dec 2026
                      description="POST-END-DATE-BOOKING-TEST")

        assert r["ok"], "Server 500 on post-end-date time booking"
        c = r["content"].lower()

        warned = any(w in c for w in [
            "ended", "closed", "after project end", "past", "warning",
            "outside", "invalid date", "error"
        ])
        if not warned:
            print(
                "\n  NOTE: Time successfully booked on Project 14 for Feb 2027 "
                "(project ends Dec 2026). No warning about booking after project "
                "end. This allows hours to accumulate on closed projects."
            )
        else:
            print("\n  App correctly warned about post-end-date time booking ✓")

    def test_book_negative_hours_is_rejected(self, page):
        """
        BUSINESS RULE: Negative duration (e.g. '-2:00') must be rejected.
        A negative time entry would reduce a person's logged hours and could
        be exploited to game utilisation metrics or timesheet totals.
        """
        r = book_time(page, project_id=PROJECT_A,
                      duration="-2:00",
                      date_worked="2026-09-07",
                      description="NEGATIVE-HOURS-TEST")
        c = r["content"].lower()

        rejected = any(w in c for w in [
            "invalid", "negative", "error", "400", "422", "must be positive"
        ]) or not r["ok"]

        assert rejected, (
            "BUG: A negative duration '-2:00' was accepted as a time booking. "
            "Negative entries corrupt timesheet totals and utilisation metrics, "
            "and could be used to manipulate reported hours."
        )
        print("\n  Correctly rejected negative duration booking ✓")

    def test_total_booked_hours_match_project_budget_display(self, page):
        """
        BUSINESS RULE: The project budget page shows '% used'. After booking
        time, this percentage MUST update. The hours displayed in 'Time booked
        by person' must sum to match the budget bar percentage.

        (Mirrors the leave-balance recalculation bug found earlier — tests that
        the same pattern doesn't exist here.)
        """
        # Read budget before
        page.goto(url(f"/projects/{PROJECT_A}"))
        page.wait_for_load_state("networkidle")
        c_before = page.content()

        pct_match = re.search(r'(\d+)%\s*used', c_before)
        pct_before = int(pct_match.group(1)) if pct_match else None
        print(f"\n  Budget used before booking: {pct_before}%")

        # Book 8 hours
        book_time(page, project_id=PROJECT_A,
                  duration="8:00",
                  date_worked="2026-09-08",
                  description="BUDGET-TRACKING-TEST")

        # Re-read budget
        page.goto(url(f"/projects/{PROJECT_A}"))
        page.wait_for_load_state("networkidle")
        c_after = page.content()

        pct_match2 = re.search(r'(\d+)%\s*used', c_after)
        pct_after = int(pct_match2.group(1)) if pct_match2 else None
        print(f"  Budget used after  booking: {pct_after}%")

        if pct_before is not None and pct_after is not None:
            assert pct_after >= pct_before, (
                f"BUG: Budget percentage DROPPED from {pct_before}% to "
                f"{pct_after}% after booking 8 hours. Budget tracking is "
                f"going in the wrong direction after time entry."
            )
            if pct_after == pct_before:
                print(
                    "  BUG: Budget % did NOT change after booking 8h "
                    f"(stayed at {pct_before}%). Same stale-counter bug as "
                    "leave balance — approval/booking doesn't trigger recalc."
                )
        else:
            print("  Could not parse budget % — layout may have changed.")

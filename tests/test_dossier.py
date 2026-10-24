"""Tests for the Article 14 filing dossier and the Article 14(7) routing cascade.

These are the parts with a right answer, so they get the most attention. The
worked example is deliberately a real-looking vulnerability notification: if the
field list drifts from the Regulation, this file should notice.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from docket.dossier import (
    REQUIREMENTS,
    SEVERE_TEST,
    Clock,
    Draft,
    Path,
    Stage,
    example_dossier,
    schedule,
)
from docket.routing import MEMBER_STATES, route

UTC = timezone.utc
AWARE = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)


class TestCoverage(unittest.TestCase):
    """Every path/stage pair the Regulation creates must have a field list."""

    def test_all_six_combinations_exist(self):
        self.assertEqual(len(REQUIREMENTS), 6)
        for path in Path:
            for stage in Stage:
                self.assertIn((path, stage), REQUIREMENTS)

    def test_every_requirement_cites_article_14(self):
        for reqs in REQUIREMENTS.values():
            for r in reqs:
                self.assertTrue(r.cite.startswith("14("), r)

    def test_each_stage_has_at_least_one_hard_requirement(self):
        for key, reqs in REQUIREMENTS.items():
            self.assertTrue(any(r.required for r in reqs), key)

    def test_vulnerability_notification_matches_the_six_limbs(self):
        """Article 14(2)(b) lists exactly (i) to (vi)."""
        cites = [r.cite for r in REQUIREMENTS[(Path.VULNERABILITY, Stage.NOTIFICATION)]]
        self.assertEqual(cites, [
            "14(2)(b)(i)", "14(2)(b)(ii)", "14(2)(b)(iii)",
            "14(2)(b)(iv)", "14(2)(b)(v)", "14(2)(b)(vi)",
        ])

    def test_incident_notification_matches_its_five_limbs(self):
        cites = [r.cite for r in REQUIREMENTS[(Path.INCIDENT, Stage.NOTIFICATION)]]
        self.assertEqual(cites, [
            "14(4)(b)(i)", "14(4)(b)(ii)", "14(4)(b)(iii)",
            "14(4)(b)(iv)", "14(4)(b)(v)",
        ])

    def test_final_reports_match_their_three_limbs(self):
        v = [r.cite for r in REQUIREMENTS[(Path.VULNERABILITY, Stage.FINAL)]]
        i = [r.cite for r in REQUIREMENTS[(Path.INCIDENT, Stage.FINAL)]]
        self.assertEqual(v, ["14(2)(c)(i)", "14(2)(c)(ii)", "14(2)(c)(iii)"])
        self.assertEqual(i, ["14(4)(c)(i)", "14(4)(c)(ii)", "14(4)(c)(iii)"])

    def test_severe_incident_test_has_both_limbs_of_14_5(self):
        self.assertEqual(len(SEVERE_TEST), 2)
        self.assertIn("integrity", SEVERE_TEST[0][1])
        self.assertIn("malicious code", SEVERE_TEST[1][1])


class TestClocks(unittest.TestCase):
    """The clocks are the product. An off-by-a-day here is the whole failure."""

    def test_early_warning_is_24_hours(self):
        c = schedule(Path.VULNERABILITY, AWARE)
        self.assertEqual(c[0].due, AWARE + timedelta(hours=24))

    def test_notification_is_72_hours(self):
        c = schedule(Path.VULNERABILITY, AWARE)
        self.assertEqual(c[1].due, AWARE + timedelta(hours=72))

    def test_vulnerability_final_is_14_days_after_the_fix(self):
        fix = AWARE + timedelta(days=9)
        c = schedule(Path.VULNERABILITY, AWARE, fix_available_at=fix)
        self.assertEqual(c[2].due, fix + timedelta(days=14))

    def test_vulnerability_final_is_absent_without_a_fix(self):
        """Article 14(2)(c) is anchored to the fix, so there is no date to
        invent before one exists. Better to omit than to guess."""
        c = schedule(Path.VULNERABILITY, AWARE)
        self.assertEqual(len(c), 2)

    def test_incident_final_is_one_month_after_submission(self):
        sent = AWARE + timedelta(hours=30)
        c = schedule(Path.INCIDENT, AWARE, notification_sent_at=sent)
        self.assertEqual(c[2].due, sent + timedelta(days=30))

    def test_incident_final_falls_back_to_the_72h_mark(self):
        c = schedule(Path.INCIDENT, AWARE)
        self.assertEqual(c[2].due, AWARE + timedelta(hours=72, days=30))

    def test_incident_and_vulnerability_anchors_differ(self):
        """Same fix time, different final-report dates — this is the trap."""
        fix = AWARE + timedelta(days=7)
        v = schedule(Path.VULNERABILITY, AWARE, fix_available_at=fix)[2].due
        sent = AWARE + timedelta(hours=72)
        i = schedule(Path.INCIDENT, AWARE, notification_sent_at=sent)[2].due
        self.assertNotEqual(v, i)

    def test_naive_datetimes_are_treated_as_utc(self):
        naive = datetime(2026, 10, 24, 9, 0)
        c = schedule(Path.INCIDENT, naive)
        self.assertEqual(c[0].due.tzinfo, UTC)

    def test_overdue_is_detected(self):
        c = Clock(Stage.EARLY_WARNING, datetime.now(UTC) - timedelta(hours=2), "x")
        self.assertTrue(c.is_overdue)
        self.assertIn("OVERDUE", c.human())

    def test_future_clock_says_due(self):
        c = Clock(Stage.NOTIFICATION, datetime.now(UTC) + timedelta(hours=5), "x")
        self.assertFalse(c.is_overdue)
        self.assertIn("due in", c.human())

    def test_each_clock_names_its_provision(self):
        for c in schedule(Path.INCIDENT, AWARE):
            self.assertIn("Article 14", c.basis)


class TestRouting(unittest.TestCase):
    """Article 14(7) is a cascade. The order is the whole point."""

    def test_main_establishment_wins_outright(self):
        r = route(main_establishment="DE", employees_by_state={"FR": 900})
        self.assertEqual(r.state, "DE")
        self.assertEqual(r.branch, "main_establishment")

    def test_employees_break_a_tie_when_main_establishment_unknown(self):
        r = route(employees_by_state={"DE": 120, "IE": 40, "PL": 10})
        self.assertEqual(r.state, "DE")
        self.assertEqual(r.branch, "employees")

    def test_zero_headcount_does_not_qualify(self):
        r = route(employees_by_state={"DE": 0, "IE": 5})
        self.assertEqual(r.state, "IE")

    def test_representative_beats_importer(self):
        r = route(has_eu_establishment=False,
                  representative=("NL", 10), importer=("DE", 400))
        self.assertEqual(r.state, "NL")
        self.assertEqual(r.branch, "representative")

    def test_importer_beats_distributor(self):
        r = route(has_eu_establishment=False,
                  importer=("DE", 400), distributor=("FR", 900))
        self.assertEqual(r.state, "DE")

    def test_distributor_beats_users(self):
        r = route(has_eu_establishment=False,
                  distributor=("FR", 20), users=("ES", 50000))
        self.assertEqual(r.state, "FR")

    def test_users_is_the_last_resort_and_is_sticky(self):
        r = route(has_eu_establishment=False, users=("ES", 50000))
        self.assertEqual(r.state, "ES")
        self.assertTrue(r.sticky)

    def test_only_the_users_branch_is_sticky(self):
        for kwargs in ({"representative": ("NL", 5)},
                       {"importer": ("DE", 5)},
                       {"distributor": ("FR", 5)}):
            r = route(has_eu_establishment=False, **kwargs)
            self.assertFalse(r.sticky, kwargs)

    def test_no_facts_means_no_answer(self):
        r = route(has_eu_establishment=False)
        self.assertFalse(r.resolved)
        self.assertTrue(r.missing)
        self.assertIn("No CSIRT can be named", r.explain())

    def test_eu_establishment_without_detail_asks_rather_than_guesses(self):
        r = route(has_eu_establishment=True)
        self.assertFalse(r.resolved)
        self.assertIn("employee headcount", " ".join(r.missing))

    def test_non_eu_code_is_rejected(self):
        with self.assertRaises(ValueError):
            route(main_establishment="US")
        with self.assertRaises(ValueError):
            route(has_eu_establishment=False, users=("GB", 10))

    def test_all_27_member_states_present(self):
        self.assertEqual(len(MEMBER_STATES), 27)
        for code in ("DE", "FR", "IE", "PL", "ES", "SE", "HR"):
            self.assertIn(code, MEMBER_STATES)
        self.assertNotIn("GB", MEMBER_STATES)


class TestDraft(unittest.TestCase):

    def test_example_is_complete(self):
        d = example_dossier()
        self.assertEqual(d.gaps(), [])
        self.assertEqual(d.completeness(), 1.0)

    def test_missing_required_field_is_reported(self):
        d = example_dossier()
        del d.facts["vulnerability_nature"]
        self.assertEqual([r.key for r in d.gaps()], ["vulnerability_nature"])
        self.assertLess(d.completeness(), 1.0)

    def test_as_available_field_may_be_empty_without_being_a_gap(self):
        d = Draft(path=Path.VULNERABILITY, stage=Stage.NOTIFICATION,
                  product="p", manufacturer="m",
                  facts={"product_information": "x", "vulnerability_nature": "y",
                         "exploit_nature": "z", "measures_taken": "a",
                         "measures_for_users": "b"})
        self.assertEqual(d.gaps(), [])
        self.assertEqual(d.completeness(), 1.0)

    def test_json_cites_every_field(self):
        payload = example_dossier().as_json()
        for key, body in payload["fields"].items():
            self.assertTrue(body["cite"].startswith("14("), key)

    def test_json_names_the_provision(self):
        payload = example_dossier().as_json()
        self.assertEqual(payload["provision"], "Article 14(2)(b)")

    def test_markdown_flags_missing_fields(self):
        d = example_dossier()
        del d.facts["measures_for_users"]
        md = d.as_markdown()
        self.assertIn("— MISSING", md)

    def test_markdown_includes_the_addressee(self):
        r = route(main_establishment="DE")
        md = example_dossier().as_markdown(r)
        self.assertIn("CSIRT of Germany", md)
        self.assertIn("Article 14(7)", md)

    def test_dossier_never_claims_to_have_filed(self):
        md = example_dossier().as_markdown().lower()
        self.assertIn("not a filing", md)
        for bad in ("submitted successfully", "filed with", "we have reported"):
            self.assertNotIn(bad, md)


if __name__ == "__main__":
    unittest.main()

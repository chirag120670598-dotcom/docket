"""CLI surface tests. These run the real parser, not a mock of it."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import date, datetime, timedelta, timezone

from docket.cli import main, parse_when


def run(*argv):
    """Call the CLI the way a shell would, including what sys.exit("msg") does.

    ``sys.exit`` with a string prints it to stderr and exits 1 when it reaches
    the top level. Redirecting stdout/stderr in-process swallows that, so the
    harness has to reproduce it or the tests would bless behaviour no user sees.
    """
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
    except SystemExit as exc:
        if isinstance(exc.code, str):
            err.write(exc.code + "\n")
            code = 1
        else:
            code = 0 if exc.code is None else exc.code
    return code, out.getvalue(), err.getvalue()


class TestParseWhen(unittest.TestCase):

    def test_now(self):
        self.assertLess(
            abs((parse_when("now") - datetime.now(timezone.utc)).total_seconds()), 5)

    def test_hours_ago(self):
        got = parse_when("3h ago")
        want = datetime.now(timezone.utc) - timedelta(hours=3)
        self.assertLess(abs((got - want).total_seconds()), 5)

    def test_bare_duration_means_ago(self):
        got = parse_when("2d")
        want = datetime.now(timezone.utc) - timedelta(days=2)
        self.assertLess(abs((got - want).total_seconds()), 5)

    def test_from_now_is_the_future(self):
        self.assertGreater(parse_when("2d from now"), datetime.now(timezone.utc))

    def test_iso_timestamp(self):
        self.assertEqual(parse_when("2026-11-02T09:00Z"),
                         datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc))

    def test_minutes(self):
        got = parse_when("90 mins ago")
        self.assertLess(abs((got - (datetime.now(timezone.utc)
                                     - timedelta(minutes=90))).total_seconds()), 5)

    def test_nonsense_exits_rather_than_guessing(self):
        with self.assertRaises(SystemExit):
            parse_when("sometime last tuesday")


class TestDeadlines(unittest.TestCase):

    def test_eu_software_small_returns_entries(self):
        code, out, _ = run("deadlines", "--market", "EU",
                           "--product", "software", "--size", "small")
        self.assertEqual(code, 0)
        self.assertIn("deadline(s) apply", out)
        self.assertIn("Cyber Resilience Act", out)

    def test_india_software_has_no_eu_regimes(self):
        code, out, _ = run("deadlines", "--market", "IN", "--product", "software")
        self.assertEqual(code, 0)
        self.assertIn("Labour Codes", out)
        self.assertNotIn("Cyber Resilience Act", out)

    def test_json_is_parseable_and_hides_internal_keys(self):
        code, out, _ = run("deadlines", "--market", "EU",
                           "--product", "connected_device", "--json")
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertTrue(rows)
        for r in rows:
            self.assertNotIn("_days", r)
            self.assertIn("source", r)

    def test_requires_both_market_and_product(self):
        code, out, err = run("deadlines", "--market", "EU")
        self.assertNotEqual(code, 0)
        self.assertIn("at least one --market and one --product", err)

    def test_impossible_combination_says_so_honestly(self):
        """A California-only company making only services genuinely has no
        entry yet. The honest answer is to say that, not to pad the list."""
        code, out, _ = run("deadlines", "--market", "US-CA", "--product", "services")
        self.assertEqual(code, 0)
        self.assertIn("No deadline in the dataset matches", out)


class TestClock(unittest.TestCase):

    def test_incident_clock_prints_three_stages(self):
        code, out, _ = run("clock", "--path", "incident", "--aware", "5h ago")
        self.assertEqual(code, 0)
        for word in ("early warning", "notification", "final"):
            self.assertIn(word, out)

    def test_vulnerability_without_fix_warns(self):
        code, out, _ = run("clock", "--path", "vulnerability", "--aware", "1h ago")
        self.assertEqual(code, 0)
        self.assertIn("no --fix given", out)
        # Two clocks only. Checked on the JSON because the human output
        # explains the missing third clock in prose that mentions "final".
        code, js, _ = run("clock", "--path", "vulnerability",
                          "--aware", "1h ago", "--json")
        payload = json.loads(js)
        self.assertEqual([r["stage"] for r in payload["clocks"]],
                         ["early_warning", "notification"])
        self.assertIn("no fix was supplied", payload["note"])

    def test_vulnerability_with_fix_has_a_final(self):
        code, out, _ = run("clock", "--path", "vulnerability",
                           "--aware", "1d ago", "--fix", "2d ago")
        self.assertEqual(code, 0)
        self.assertIn("final", out)

    def test_json_output(self):
        code, out, _ = run("clock", "--path", "incident",
                           "--aware", "2026-10-24T09:00Z", "--json")
        self.assertEqual(code, 0)
        rows = json.loads(out)["clocks"]
        self.assertEqual([r["stage"] for r in rows],
                         ["early_warning", "notification", "final"])

    def test_overdue_notification_is_reported(self):
        code, out, _ = run("clock", "--path", "incident",
                           "--aware", "10d ago", "--json")
        rows = json.loads(out)["clocks"]
        self.assertTrue(all(r["overdue"] for r in rows if r["stage"] != "final"))


class TestRoute(unittest.TestCase):

    def test_main_establishment(self):
        code, out, _ = run("route", "--main-establishment", "IE")
        self.assertEqual(code, 0)
        self.assertIn("Ireland", out)

    def test_employees_are_parsed_as_numbers(self):
        code, out, _ = run("route", "--employees", "DE=120", "--employees", "IE=40")
        self.assertEqual(code, 0)
        self.assertIn("Germany", out)

    def test_bad_state_is_a_clean_error_not_a_traceback(self):
        code, out, err = run("route", "--main-establishment", "US")
        self.assertEqual(code, 1)
        self.assertIn("invalid Member State", err)
        self.assertNotIn("Traceback", err)

    def test_bad_employees_syntax(self):
        code, _, err = run("route", "--employees", "DE")
        self.assertEqual(code, 1)
        self.assertIn("CODE=COUNT", err)

    def test_unresolved_returns_exit_2(self):
        code, out, _ = run("route", "--no-eu-establishment")
        self.assertEqual(code, 2)
        self.assertIn("No CSIRT can be named", out)

    def test_json(self):
        code, out, _ = run("route", "--no-eu-establishment",
                           "--users", "ES", "--users-count", "100", "--json")
        payload = json.loads(out)
        self.assertEqual(payload["state"], "ES")
        self.assertTrue(payload["sticky"])


class TestDossierAndCheck(unittest.TestCase):

    def test_default_is_the_worked_example(self):
        code, out, _ = run("dossier")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["path"], "vulnerability")
        self.assertEqual(payload["gaps"], [])

    def test_markdown_mode(self):
        code, out, _ = run("dossier", "--markdown")
        self.assertIn("# Notification", out)

    def test_custom_draft_reports_gaps(self):
        code, out, _ = run("dossier", "--path", "incident", "--stage", "final",
                           "--product", "Widget", "--manufacturer", "ACME")
        payload = json.loads(out)
        self.assertEqual(len(payload["gaps"]), 3)

    def test_requirements_lists_all_six(self):
        code, out, _ = run("requirements")
        self.assertEqual(code, 0)
        self.assertIn("vulnerability · early_warning", out)
        self.assertIn("incident · final", out)
        self.assertIn("Article 14(5)", out)

    def test_check_passes(self):
        code, out, _ = run("check")
        self.assertEqual(code, 0, out)
        self.assertIn("no problems found", out)


class TestExport(unittest.TestCase):

    def test_ics_has_a_calendar_and_events(self):
        code, out, _ = run("export", "--format", "ics")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("BEGIN:VCALENDAR"))
        self.assertTrue(out.rstrip().endswith("END:VCALENDAR"))
        self.assertEqual(out.count("BEGIN:VEVENT"), out.count("END:VEVENT"))
        self.assertEqual(out.count("BEGIN:VEVENT"), 23)

    def test_ics_uses_crlf(self):
        code, out, _ = run("export", "--format", "ics")
        self.assertIn("\r\n", out)

    def test_ics_folded_description_does_not_break_lines(self):
        """A raw newline inside DESCRIPTION silently corrupts the calendar."""
        code, out, _ = run("export", "--format", "ics")
        for line in out.split("\r\n"):
            self.assertNotIn("\n", line)

    def test_markdown_export(self):
        code, out, _ = run("export", "--format", "md")
        self.assertIn("| Date | Regime |", out)
        self.assertGreater(out.count("\n"), 20)

    def test_json_export_is_the_whole_dataset(self):
        code, out, _ = run("export", "--format", "json")
        self.assertEqual(len(json.loads(out)), 23)

    def test_filtered_export_is_smaller(self):
        code, out, _ = run("export", "--format", "json",
                           "--market", "IN", "--product", "software")
        rows = json.loads(out)
        self.assertTrue(0 < len(rows) < 23)


if __name__ == "__main__":
    unittest.main()

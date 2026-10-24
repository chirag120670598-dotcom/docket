"""Tests for the Docket dataset and build.

The site is a few hundred lines of JavaScript, but the thing that actually
breaks a deadline tracker is the *data*: a date that moved, a source that 404s,
an entry that claims to apply to everybody. So the tests spend their effort
there.
"""

from __future__ import annotations

import json
import re
import unittest
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docket" / "data" / "deadlines.json"
DIST = ROOT / "dist" / "index.html"

import sys
sys.path.insert(0, str(ROOT / "tools"))
import build as builder  # noqa: E402


def load_entries() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


# The same predicate the browser runs. Duplicated on purpose: if the JS and this
# ever disagree, one of them is wrong and a test should say so.
def applies(entry: dict, markets: set, products: set, size: str | None) -> bool:
    a = entry["applies_if"]
    if not set(a["markets"]) & markets:
        return False
    if not set(a["products"]) & products:
        return False
    if size and size not in a["sizes"]:
        return False
    roles = {"employer"}
    if products & {"connected_device", "physical_goods"}:
        roles |= {"manufacturer", "importer"}
    if products & {"software", "ai_system"}:
        roles |= {"provider", "manufacturer"}
    if products & {"services"}:
        roles.add("provider")
    if "ai_system" in products:
        roles.add("deployer")
    if not set(a["roles"]) & roles:
        return False
    return True


def matching(entries, markets, products, size=None):
    return {e["id"] for e in entries
            if applies(e, set(markets), set(products), size)}


class TestSchema(unittest.TestCase):

    def setUp(self):
        self.doc = load_entries()
        self.entries = self.doc["deadlines"]

    def test_dataset_validates(self):
        today = date.today()
        errors = []
        for i, e in enumerate(self.entries):
            errors.extend(builder.check(e, i, today))
        self.assertEqual(errors, [], "\n".join(errors))

    def test_ids_are_unique(self):
        ids = [e["id"] for e in self.entries]
        self.assertEqual(len(ids), len(set(ids)))

    def test_dates_are_well_formed_and_sorted_by_parser(self):
        for e in self.entries:
            datetime.strptime(e["date"], "%Y-%m-%d")
            datetime.strptime(e["verified"], "%Y-%m-%d")

    def test_every_entry_has_a_source_url(self):
        for e in self.entries:
            self.assertTrue(e["source"]["url"].startswith("http"), e["id"])
            self.assertGreater(len(e["source"]["label"]), 10, e["id"])

    def test_no_entry_verifies_itself_in_the_future(self):
        today = date.today()
        for e in self.entries:
            self.assertLessEqual(
                datetime.strptime(e["verified"], "%Y-%m-%d").date(), today, e["id"])

    def test_summaries_stay_readable(self):
        for e in self.entries:
            self.assertLessEqual(len(e["summary"]), 400, e["id"])

    def test_confidence_is_declared_and_honest(self):
        """'primary' is a claim about what was read, so it must be rare enough
        to be believable and never used for an amended date we only read about."""
        values = {e["confidence"] for e in self.entries}
        self.assertLessEqual(values, {"primary", "reported"})
        primary = [e["id"] for e in self.entries if e["confidence"] == "primary"]
        self.assertGreaterEqual(len(primary), 3)
        self.assertLess(len(primary), len(self.entries))

    def test_jurisdictions_are_covered(self):
        js = {e["jurisdiction"] for e in self.entries}
        for j in ("EU", "IN"):
            self.assertIn(j, js)


class TestFilterSemantics(unittest.TestCase):
    """Worked cases. If the product's core promise breaks, it breaks here."""

    def setUp(self):
        self.entries = load_entries()["deadlines"]

    def test_eu_software_large_hits_the_cra_and_gdpr(self):
        ids = matching(self.entries, ["EU"], ["software"], "large")
        self.assertIn("eu-cra-art14", ids)
        self.assertIn("eu-gdpr", ids)
        self.assertIn("eu-cra-fines", ids)

    def test_india_company_does_not_get_eu_deadlines(self):
        ids = matching(self.entries, ["IN"], ["software"], "small")
        for eid in ids:
            entry = [e for e in self.entries if e["id"] == eid][0]
            self.assertIn("IN", entry["applies_if"]["markets"], eid)
        self.assertIn("in-labour-codes", ids)
        self.assertIn("in-epf-ceiling", ids)
        self.assertNotIn("eu-cra-art14", ids)

    def test_micro_employer_in_india_still_gets_labour_codes(self):
        """The Code on Wages applies to every employer regardless of size."""
        ids = matching(self.entries, ["IN"], ["services"], "micro")
        self.assertIn("in-labour-codes", ids)

    def test_services_only_never_triggers_product_safety_law(self):
        ids = matching(self.entries, ["EU"], ["services"], "large")
        self.assertNotIn("eu-cra-art14", ids)
        self.assertNotIn("eu-machinery", ids)
        self.assertNotIn("eu-pld", ids)
        self.assertIn("eu-gdpr", ids)

    def test_hardware_in_eu_hits_machinery_and_cra(self):
        ids = matching(self.entries, ["EU"], ["connected_device"], "medium")
        self.assertIn("eu-cra-art14", ids)
        self.assertIn("eu-machinery", ids)

    def test_small_company_is_excluded_from_250_plus_reporting(self):
        small = matching(self.entries, ["EU"], ["software"], "small")
        large = matching(self.entries, ["EU"], ["software"], "large")
        self.assertNotIn("eu-pay-transparency-report", small)
        self.assertIn("eu-pay-transparency-report", large)

    def test_california_only_gets_california_plus_nothing_eu(self):
        ids = matching(self.entries, ["US-CA"], ["physical_goods"], "small")
        self.assertIn("us-ca-sb54", ids)
        for eid in ids:
            entry = [e for e in self.entries if e["id"] == eid][0]
            self.assertEqual(entry["jurisdiction"], "US-CA", eid)

    def test_every_entry_is_reachable_by_some_answer(self):
        """An entry no combination can surface is dead weight in the dataset."""
        reachable = set()
        for j in builder.JURISDICTIONS:
            for p in builder.PRODUCTS:
                for s in builder.SIZES:
                    reachable |= matching(self.entries, [j], [p], s)
        unreachable = [e["id"] for e in self.entries if e["id"] not in reachable]
        self.assertEqual(unreachable, [], f"unreachable entries: {unreachable}")

    def test_a_broad_answer_returns_a_manageable_list(self):
        ids = matching(self.entries, ["EU", "IN", "US-CA"],
                       list(builder.PRODUCTS), "large")
        self.assertGreater(len(ids), 10)
        self.assertLess(len(ids), 30)


class TestBuild(unittest.TestCase):

    def test_build_succeeds_and_is_idempotent(self):
        self.assertEqual(builder.build(), 0)
        first = DIST.read_text(encoding="utf-8")
        self.assertEqual(builder.build(), 0)
        self.assertEqual(first, DIST.read_text(encoding="utf-8"))

    def test_placeholder_is_consumed(self):
        builder.build()
        self.assertNotIn("__DOCKET_DATA__", DIST.read_text(encoding="utf-8"))

    def test_embedded_json_matches_the_source_file(self):
        builder.build()
        html = DIST.read_text(encoding="utf-8")
        m = re.search(
            r'<script id="docket-data" type="application/json">(.*?)</script>',
            html, re.S)
        self.assertIsNotNone(m)
        embedded = json.loads(m.group(1))
        source = load_entries()
        self.assertEqual(len(embedded["deadlines"]), len(source["deadlines"]))
        self.assertEqual({e["id"] for e in embedded["deadlines"]},
                         {e["id"] for e in source["deadlines"]})

    def test_status_and_days_are_computed(self):
        builder.build()
        html = DIST.read_text(encoding="utf-8")
        m = re.search(
            r'<script id="docket-data" type="application/json">(.*?)</script>',
            html, re.S)
        data = json.loads(m.group(1))
        today = date.today()
        for e in data["deadlines"]:
            expected = (datetime.strptime(e["date"], "%Y-%m-%d").date() - today).days
            self.assertEqual(e["days"], expected, e["id"])
            self.assertEqual(e["status"], "upcoming" if expected > 0 else "live", e["id"])

    def test_upcoming_entries_come_first(self):
        builder.build()
        html = DIST.read_text(encoding="utf-8")
        m = re.search(
            r'<script id="docket-data" type="application/json">(.*?)</script>',
            html, re.S)
        rows = json.loads(m.group(1))["deadlines"]
        statuses = [r["status"] for r in rows]
        if "live" in statuses and "upcoming" in statuses:
            self.assertEqual(statuses.index("live") > statuses.index("upcoming"), True)

    def test_output_is_self_contained(self):
        """No external scripts, no fonts, no CDN. It must work from a file:// URL
        and inside a sandboxed iframe."""
        builder.build()
        html = DIST.read_text(encoding="utf-8")
        self.assertNotIn("<script src=", html)
        self.assertNotIn("<link rel=\"stylesheet\"", html)
        self.assertNotIn("@import", html)

    def test_no_analytics_or_trackers(self):
        builder.build()
        html = DIST.read_text(encoding="utf-8").lower()
        for needle in ("google-analytics", "gtag(", "plausible", "mixpanel",
                       "facebook.net", "hotjar", "segment.com"):
            self.assertNotIn(needle, html)

    def test_no_donation_coercion_patterns(self):
        """A support link is fine. Manufactured urgency, guilt copy, fake
        countdowns or 'others are donating' pressure are not, and the build
        should fail if someone adds them."""
        builder.build()
        html = DIST.read_text(encoding="utf-8").lower()
        for needle in ("only today", "others have donated", "act now",
                       "you will lose access", "limited time", "hurry",
                       "don't miss out", "last chance"):
            self.assertNotIn(needle, html)


if __name__ == "__main__":
    unittest.main()

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
DIST = ROOT / "site" / "index.html"

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


class TestGeneratedSite(unittest.TestCase):
    """The site is now more than one file. Each artefact has one job and one
    way to be wrong, so each gets checked."""

    @classmethod
    def setUpClass(cls):
        builder.build()
        cls.entries = load_entries()["deadlines"]
        cls.site = ROOT / "site"

    def test_index_exists(self):
        self.assertTrue((self.site / "index.html").is_file())

    def test_every_entry_gets_a_page(self):
        for e in self.entries:
            page = self.site / "regime" / f"{e['slug']}.html"
            self.assertTrue(page.is_file(), e["slug"])

    def test_no_unfilled_placeholders_anywhere(self):
        for f in self.site.rglob("*.html"):
            self.assertNotIn("{{", f.read_text(encoding="utf-8"), f.name)

    def test_regime_page_carries_the_essentials(self):
        for e in self.entries:
            h = (self.site / "regime" / f"{e['slug']}.html").read_text(encoding="utf-8")
            self.assertIn("<title>", h)
            self.assertIn('name="description"', h)
            self.assertIn('rel="canonical"', h)
            self.assertIn("application/ld+json", h)
            self.assertIn(e["source"]["url"], h, e["slug"])
            self.assertIn("not legal advice", h.lower())

    def test_every_title_carries_its_date(self):
        """The date is what people search for. Truncation must never eat it."""
        import re as _re
        for e in self.entries:
            h = (self.site / "regime" / f"{e['slug']}.html").read_text(encoding="utf-8")
            import html as _html
            title = _html.unescape(
                _re.search(r"<title>(.*?)</title>", h, _re.S).group(1))
            # Measure what a browser shows, not the entity-escaped source:
            # an apostrophe becomes &#x27; and inflates the raw byte count.
            self.assertLessEqual(len(title), 70, f"{e['slug']}: title too long ({title!r})")
            d = datetime.strptime(e["date"], "%Y-%m-%d").date()
            stamp = f"{d.day} {d.strftime('%B %Y')}"
            self.assertIn(stamp, title, f"{e['slug']}: title lost its date ({title!r})")
            self.assertTrue(title.endswith("| Docket") or len(title) <= 70, e["slug"])

    def test_regime_page_states_the_date(self):
        h = (self.site / "regime" / "eu-ai-act-high-risk-annex-iii-2027.html").read_text()
        self.assertIn("2 December 2027", h)

    def test_regime_pages_link_into_the_tool_with_an_answer(self):
        h = (self.site / "regime" / "eu-cyber-resilience-act-article-14-reporting.html").read_text()
        # The ampersand is escaped because this is an HTML attribute, which is
        # the correct serialisation. Check what a browser will resolve to.
        self.assertIn('href="../#m=EU&amp;p=connected_device"', h)

    def test_regime_page_keeps_the_honest_badge(self):
        h = (self.site / "regime" / "eu-ai-act-high-risk-annex-iii-2027.html").read_text()
        self.assertIn("secondary source", h)

    def test_pages_share_one_stylesheet(self):
        """Inlined, not linked — the preview iframe has no network."""
        for f in self.site.rglob("*.html"):
            self.assertNotIn('<link rel="stylesheet"', f.read_text(encoding="utf-8"))
            self.assertNotIn("@import", f.read_text(encoding="utf-8"))

    def read_ics(self):
        # newline="" preserves the CRLF that RFC 5545 requires; read_text()
        # would translate them away and hide a broken calendar.
        with open(self.site / "deadlines.ics", encoding="utf-8", newline="") as f:
            return f.read()

    def test_calendar_feed_is_wellformed(self):
        feed = self.read_ics()
        self.assertTrue(feed.startswith("BEGIN:VCALENDAR"))
        self.assertTrue(feed.rstrip().endswith("END:VCALENDAR"))
        self.assertEqual(feed.count("BEGIN:VEVENT"), len(self.entries))
        self.assertEqual(feed.count("END:VEVENT"), len(self.entries))
        self.assertEqual(feed.count("BEGIN:VALARM"), len(self.entries))
        for line in feed.split("\r\n"):
            self.assertNotIn("\n", line, "raw newline inside a calendar line")

    def test_calendar_feed_has_one_uid_per_entry(self):
        feed = self.read_ics()
        for e in self.entries:
            self.assertIn(f"UID:{e['id']}@docket", feed)

    def test_calendar_reminder_comes_before_the_date(self):
        feed = self.read_ics()
        self.assertIn("TRIGGER:-P14D", feed)

    def test_sitemap_lists_every_page(self):
        import xml.etree.ElementTree as ET
        tree = ET.parse(self.site / "sitemap.xml")
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [u.find("s:loc", ns).text for u in tree.getroot().findall("s:url", ns)]
        self.assertEqual(len(locs), len(self.entries) + 2)
        for e in self.entries:
            self.assertIn(f"/regime/{e['slug']}.html", " ".join(locs))
        self.assertTrue(all(l.startswith("http") for l in locs))

    def test_robots_points_at_the_sitemap(self):
        r = (self.site / "robots.txt").read_text(encoding="utf-8")
        self.assertIn("Sitemap:", r)
        self.assertIn("sitemap.xml", r)
        self.assertNotIn("Disallow: /", r)

    def test_changes_page_exists_and_names_the_ai_act_move(self):
        h = (self.site / "changes.html").read_text(encoding="utf-8")
        self.assertIn("2 December 2027", h)
        self.assertIn("2026/1744", h)
        self.assertIn("not an automated diff", h)

    def test_every_internal_link_resolves(self):
        """A static site has no 404 handler to catch a typo, so the build has to."""
        import re as _re
        from urllib.parse import urlparse, unquote
        broken = []
        for f in self.site.rglob("*.html"):
            rel_dir = f.parent.relative_to(self.site)
            text = f.read_text(encoding="utf-8")
            for href in _re.findall(r'href="([^"]+)"', text):
                if href.startswith(("http://", "https://", "mailto:", "data:", "#")):
                    continue
                target = urlparse(href)
                path = unquote(target.path)
                if not path:
                    continue
                dest = (self.site / rel_dir / path) if not path.startswith("/") \
                    else (self.site / path.lstrip("/"))
                if path.endswith("/"):
                    dest = dest / "index.html"
                dest = Path(str(dest).replace("\\", "/"))
                try:
                    dest = dest.resolve()
                except OSError:
                    pass
                if not dest.exists():
                    broken.append(f"{f.name} -> {href}")
        self.assertEqual(broken, [], "broken internal links: " + ", ".join(broken))

    def test_no_absolute_localhost_links(self):
        for f in self.site.rglob("*.html"):
            low = f.read_text(encoding="utf-8").lower()
            self.assertNotIn("localhost", low, f.name)
            self.assertNotIn("127.0.0.1", low, f.name)

    def test_no_page_ships_coercion_copy(self):
        for f in self.site.rglob("*.html"):
            low = f.read_text(encoding="utf-8").lower()
            for needle in ("only today", "others have donated", "act now",
                           "limited time", "last chance", "hurry"):
                self.assertNotIn(needle, low, f.name)


if __name__ == "__main__":
    unittest.main()

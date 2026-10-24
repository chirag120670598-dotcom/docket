#!/usr/bin/env node
/**
 * Assert a generated regime page still says what it is supposed to say.
 *
 * The AI Act high-risk page is the one that would embarrass the project most if
 * it silently reverted to the old 2 August 2026 date, so it is pinned here.
 * Date movements are exactly the failure this project exists to prevent, and
 * pinning the corrected value is how a regression gets caught.
 *
 *   node tools/check_regime.js
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const PAGE = "site/regime/eu-ai-act-high-risk-annex-iii-2027.html";
const EXPECTED_DATE = "2 December 2027";
const OLD_DATE = "2 August 2026";

const file = path.join(__dirname, "..", PAGE);
if (!fs.existsSync(file)) {
  console.error(`missing ${PAGE} — run the build first`);
  process.exit(1);
}

const dom = new JSDOM(fs.readFileSync(file, "utf8"));
const d = dom.window.document;
const problems = [];

const bigdate = d.querySelector(".bigdate");
if (!bigdate) problems.push("no .bigdate element");
else if (bigdate.textContent.trim() !== EXPECTED_DATE) {
  problems.push(`date is ${JSON.stringify(bigdate.textContent.trim())}, expected ${EXPECTED_DATE}`);
}

const ld = d.querySelector('script[type="application/ld+json"]');
if (!ld) problems.push("no JSON-LD structured data");
else {
  try {
    const parsed = JSON.parse(ld.textContent);
    if (parsed.about && parsed.about.startDate !== "2027-12-02") {
      problems.push(`structured data startDate is ${parsed.about.startDate}`);
    }
  } catch (e) {
    problems.push("JSON-LD does not parse: " + e.message);
  }
}

const body = d.body.textContent;
if (!/Omnibus|2026\/1744/.test(body)) {
  problems.push("page does not name the instrument that moved the date");
}
// Mentioning the old date is the point — but only in the same breath as the
// fact that it moved. An old date stated flatly is the failure mode.
if (body.includes(OLD_DATE) && !/moved|defer|supersed|no longer/i.test(body)) {
  problems.push(`page states ${OLD_DATE} with no explanation that it was superseded`);
}
if (!d.querySelector('link[rel="canonical"]')) problems.push("no canonical link");
if (!d.title.includes(EXPECTED_DATE)) {
  problems.push(`title does not carry the date: ${JSON.stringify(d.title)}`);
}
const canonical = d.querySelector('link[rel="canonical"]');
if (canonical && !canonical.href.includes("eu-ai-act-high-risk-annex-iii-2027")) {
  problems.push("canonical points somewhere else");
}

if (problems.length) {
  for (const p of problems) console.error("  FAIL  " + p);
  process.exit(1);
}

console.log(`check_regime: ${PAGE} ok — ${EXPECTED_DATE}`);

# Docket

[![test](https://github.com/chirag120670598-dotcom/docket/actions/workflows/test.yml/badge.svg)](https://github.com/chirag120670598-dotcom/docket/actions/workflows/test.yml)
[![pages](https://github.com/chirag120670598-dotcom/docket/actions/workflows/pages.yml/badge.svg)](https://chirag120670598-dotcom.github.io/docket/)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

### **[Open the site →](https://chirag120670598-dotcom.github.io/docket/)**

**Every compliance deadline that binds your company, dated, priced and sourced — and the Cyber Resilience Act Article 14 filing clock that most summaries get wrong.**

[Docket the website](https://github.com/chirag120670598-dotcom/docket) · `python3 tools/build.py` · zero dependencies

---

## The finding

The AI Act's high-risk obligations were due on **2 August 2026**.

They are now due on **2 December 2027**.

Not because of a delay announced in a press release, but because **Regulation (EU) 2026/1744** — the Digital Omnibus on AI — was signed on 8 July 2026, published in the Official Journal on 24 July 2026, and entered into force on 27 July 2026. Annex III standalone high-risk systems moved from 2 Aug 2026 to 2 Dec 2027. Annex I product-embedded systems moved from 2 Aug 2027 to 2 Aug 2028. What did *not* move: the Article 5 prohibitions (in force since 2 February 2025) and the Article 50 transparency duties (live since 2 August 2026).

Every compliance calendar built before 24 July 2026 still shows the old date, and it shows it **confidently**. That is the failure mode this project exists to avoid. A deadline tracker is not valuable because it has a database. It is valuable because somebody re-read the instrument.

Docket records, per entry, whether the **primary instrument** was read or whether the date came from a **secondary source**. That distinction is on the page, per deadline, in a badge. It is not decoration — it is the honest confidence interval of the claim.

---

## What this is not

This is a scoping aid. It tells you what to read, by when, with what exposure. It cannot tell you whether your product falls inside a definition, and it is not legal advice. See [Limitations](#limitations) — they are specific and they matter.

---

## What the page does

Answer three questions — where you sell, what you put on the market, how many people work for you — and it returns the deadlines that bind that combination, sorted with the nearest first, each carrying:

- the date, and how long is left
- the statutory penalty tier
- a link to the instrument itself
- whether the instrument was read (`primary`) or only reported (`reported`)
- the date that entry was last checked

Your answers go into the URL, so "here is what applies to *us*" is one copied link. There is an `.ics` export of whatever you are looking at, so the deadlines land in the calendar where deadlines actually get noticed.

Nothing is transmitted. There is no backend, no analytics, no cookies, no font CDN, no login. The page is a single HTML file with the dataset inlined; it works from a USB stick.

---

## What the CLI does

The same dataset, plus the part a page cannot do: the clock.

```
$ docket clock --path incident --aware "5h ago"

incident path · aware at 2026-10-24T06:44+00:00

  early warning  2026-10-25 06:44 UTC            due in 19.0 h
                 Article 14(4)(a)
  notification   2026-10-27 06:44 UTC          due in 2.8 days
                 Article 14(4)(b)
  final          2026-11-26 06:44 UTC         due in 32.8 days
                 Article 14(4)(c) — one month after the incident notification
                 was submitted (assumes submission at the 72-hour mark)
```

**The trap the summaries miss: the two final-report clocks are anchored to different events.**

| | Vulnerability path | Severe-incident path |
|---|---|---|
| early warning | +24 h from awareness — Art. 14(2)(a) | +24 h from awareness — Art. 14(4)(a) |
| notification | +72 h from awareness — Art. 14(2)(b) | +72 h from awareness — Art. 14(4)(b) |
| final report | **+14 days after a corrective measure is available** — Art. 14(2)(c) | **+1 month after the notification was submitted** — Art. 14(4)(c) |

The vulnerability final report runs from *the fix*. The incident final report runs from *your filing*. Get those two confused and you will be late on one of them, in opposite directions depending on which path you are on.

### Which CSIRT, though

Article 14(7) is a cascade, and almost no summary of the CRA reproduces it:

1. The CSIRT of the Member State where the manufacturer has its **main establishment** — meaning where the decisions on the cybersecurity of the product are *predominantly taken*. If that cannot be determined, the Member State where the manufacturer has the **establishment with the highest number of employees** in the Union.
2. If there is **no main establishment in the Union**, in order: the Member State of the **authorised representative** acting for the highest number of products; else the **importer** placing the highest number on the market; else the **distributor** making the highest number available; else the Member State where the **highest number of users** are located.
3. And the sentence that catches people: where the user-location limb applies, the manufacturer **may submit subsequent notifications to the same CSIRT it first reported to**. Jurisdiction, once fixed by user base, sticks.

```
$ docket route --no-eu-establishment --users FR --users-count 900

File with the CSIRT of France (FR).
Basis: Article 14(7)(d) — highest number of users.
Note: because jurisdiction was fixed by user location, Article 14(7) lets you
submit subsequent notifications to this same CSIRT rather than re-deriving it
each time.
```

The router **refuses to name a Member State when the facts given cannot decide it**, and names the missing fact instead. A guess here is worse than no answer, because it looks like an answer.

### The filing itself

`docket dossier` holds the field list from the provision — Article 14(2)(b)(i)–(vi) for a vulnerability notification, 14(4)(b)(i)–(v) for an incident, (c)(i)–(iii) for either final report — checks a draft against it, and reports the gaps.

Fields marked *as available* in the Regulation are not counted as gaps when empty, because the Regulation says "general information available" rather than demanding the information. That distinction is in the data structure, not in a footnote.

```
$ docket dossier --markdown

# Notification — Vulnerability

**Instrument:** Regulation (EU) 2024/2847, Article 14(2)(b)
**Manufacturer:** Acme Controls GmbH
**Product:** Acme Hub 3000 — firmware 4.2.1 and earlier (connected building controller)

## Content required by the provision

- **General information on the product with digital elements** _14(2)(b)(i)_
  Acme Hub 3000 running firmware 4.1.0 through 4.2.1. Distributed in DE, FR, NL, PL and ES...
- **General nature of the exploit** _14(2)(b)(ii)_
  Authentication bypass in the local management interface, reachable on the LAN...
```

Every field in the output carries the limb it comes from, so a reviewer can check any single line against the text. The dossier says plainly that it **is not a filing** — the report itself goes through the ENISA single reporting platform.

### Everything else

```
docket deadlines --market EU --product software --size small   # what binds you
docket route --main-establishment DE                           # which CSIRT
docket clock --path vulnerability --aware "2d ago" --fix "6h ago"
docket dossier --path incident --stage final --field root_cause="..."
docket requirements                                            # the field lists
docket export --format ics                                     # calendar
docket check                                                   # validate the dataset
```

Add `--json` to any command for machine-readable output. `clock --json` always returns the same envelope — `{path, aware_at, clocks[], note?}` — so a caller never has to defend against two shapes.

---

## Install

```bash
git clone https://github.com/chirag120670598-dotcom/docket
cd docket

python3 -m docket deadlines --market EU --product software   # no install needed
python3 tools/build.py && open site/index.html               # build the site
python3 -m unittest discover -s tests -t .                   # 97 tests
node tools/render_test.js                                    # 43 DOM checks
```

Python 3.9+. No dependencies at all — not for the CLI, not for the build, not for the tests.

---

## The dataset

`data/deadlines.json` — 23 entries across the EU, India and California. Each one carries:

| field | meaning |
|---|---|
| `date` | the date that binds |
| `kind` | `obligation`, `deadline` or `repeal` |
| `applicability` | markets, product categories, size bands, roles |
| `source` | the instrument, by name, and a link |
| `confidence` | `primary` — the instrument was read; `reported` — a secondary source was |
| `verified` | the date it was last checked |

The build refuses to run if an entry is missing a source, dates something in the future as verified, uses a vocabulary value the site does not understand, or duplicates an id. `docket check` adds a staleness test: anything unverified for over a year fails.

Currently covered:

**EU** — Cyber Resilience Act (Art. 14 duty, Art. 64 fines), AI Act (Annex III, Annex I, Art. 50 transition), Product Liability Directive, Machinery Regulation, Data Act, Construction Products, Packaging (PPWR), Batteries, EUDR, Pay Transparency (transposition and first reports), GDPR, NIS2, CSRD as amended

**India** — the four Labour Codes, the Central Rules, the EPF wage ceiling, the state-rules target, DPDP breach notification

**California** — SB 54 producer responsibility

---

## Limitations

These are specific. Read them before relying on anything here.

- **Not legal advice, and not a substitute for it.** Applicability is modelled on markets, product category, headcount and role. Real applicability turns on definitions in the instrument — what counts as "placing on the market", whether a component makes you a manufacturer, what an "AI system" is. Those are legal questions about facts only you have.
- **`confidence: reported` means the date was not read in the instrument.** Where a date was amended after publication, the amendment is named in the source line — but if the badge says *reported*, treat the date as needing confirmation before you build a programme on it.
- **Coverage is a choice, not an accident.** Regimes are added when the instrument can be read, not when a summary of it can be found. There is no UK, no other US state, no sectoral financial regulation, no tax. A missing regime shows as a *missing answer*, which is why the empty state says so out loud rather than looking like reassurance.
- **Penalties quoted are statutory maxima.** National implementations set actual levels. The number is there to size the risk, not to predict a fine.
- **The Article 14(7) router encodes the cascade, not your facts.** It will tell you which branch a given set of facts lands on; whether those facts are true — where decisions are really taken, who really has the most users — is your call.
- **`docket dossier` checks content against the provision's field list. It does not judge adequacy.** A complete dossier can still be a bad filing.
- **The site's "as of" date is the build date, not a guarantee of freshness.** Rebuild it, or watch the repo, if that matters.
- **The staleness threshold is 120 days.** After that the build warns but still ships the entry. Hiding a stale deadline would help nobody; the warning is in the build output and the verification date is on every card.

---

## How this stays accurate

The dataset is the deliverable, so it is treated like one:

1. An entry is added only with the instrument in hand, or with `confidence: reported` and a named secondary source.
2. `python3 tools/build.py` refuses to publish a dataset with a missing source or an unknown vocabulary value.
3. `docket check` fails on anything unverified for a year.
4. The staleness warning fires at 120 days.

If you find a date that has moved and this says otherwise, that is the most valuable bug you can file. Open an issue with the instrument.

---

## License

Apache-2.0. See [LICENSE](LICENSE).

The deadline data is offered under the same terms. Use it, fork it, put it in front of your own users.

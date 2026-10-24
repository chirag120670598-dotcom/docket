#!/usr/bin/env python3
"""Validate the deadline dataset and build the whole static site.

Outputs, all from one dataset:

    site/index.html          the tool — three questions, filtered deadlines
    site/regime/<slug>.html  one page per deadline, for people arriving from search
    site/changes.html        what moved, and what it means for you
    site/deadlines.ics       the whole set as a subscribable calendar
    site/sitemap.xml         so the per-regime pages are discoverable
    site/robots.txt

Nothing generated depends on a server, a network call, or a build tool. The
page opens from a file:// URL and deploys to any static host.

Run:  python3 tools/build.py
Check only (exit 1 on problems):  python3 tools/build.py --check
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docket" / "data" / "deadlines.json"
CHANGES = ROOT / "docket" / "data" / "changes.json"
TEMPLATE = ROOT / "web" / "template.html"
REGIME_TPL = ROOT / "web" / "regime.html"
STYLE = ROOT / "web" / "style.css"
OUT = ROOT / "site"

SITE = os.environ.get("DOCKET_URL", "https://chirag120670598-dotcom.github.io/docket").rstrip("/")

JURISDICTIONS = {"EU", "IN", "US-CA", "UK", "GLOBAL"}
PRODUCTS = {"connected_device", "software", "ai_system", "physical_goods", "services"}
SIZES = {"micro", "small", "medium", "large"}
ROLES = {"manufacturer", "importer", "distributor", "provider", "deployer", "employer"}
KINDS = {"obligation", "deadline", "repeal"}
CONFIDENCE = {"primary", "reported"}

STALE_DAYS = 120

JURIS_LABEL = {"EU": "European Union", "IN": "India", "US-CA": "California",
               "UK": "United Kingdom", "GLOBAL": "Global"}
PRODUCT_LABEL = {"connected_device": "connected hardware", "software": "software",
                 "ai_system": "an AI system", "physical_goods": "physical goods",
                 "services": "services"}
SIZE_LABEL = {"micro": "1–9 employees", "small": "10–49", "medium": "50–249",
              "large": "250+"}
ROLE_LABEL = {"manufacturer": "manufacturer", "importer": "importer",
              "distributor": "distributor", "provider": "service provider",
              "deployer": "deployer", "employer": "employer"}


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def check(entry: dict, idx: int, today: date) -> list[str]:
    errs: list[str] = []
    eid = entry.get("id", f"#{idx}")

    for key in ("id", "jurisdiction", "regime", "title", "date", "kind",
                "summary", "source", "confidence", "verified", "applies_if",
                "slug", "actions"):
        if not entry.get(key):
            errs.append(f"{eid}: missing required field {key!r}")

    if entry.get("jurisdiction") not in JURISDICTIONS:
        errs.append(f"{eid}: unknown jurisdiction {entry.get('jurisdiction')!r}")
    if entry.get("kind") not in KINDS:
        errs.append(f"{eid}: unknown kind {entry.get('kind')!r}")
    if entry.get("confidence") not in CONFIDENCE:
        errs.append(f"{eid}: confidence must be one of {sorted(CONFIDENCE)}")

    slug = entry.get("slug", "")
    if slug and not all(c.isalnum() or c == "-" for c in slug):
        errs.append(f"{eid}: slug must be lowercase letters, digits and hyphens")

    actions = entry.get("actions") or []
    if isinstance(actions, list) and len(actions) < 2:
        errs.append(f"{eid}: a regime page with fewer than two actions is filler")
    for a in actions if isinstance(actions, list) else []:
        if len(a) < 30:
            errs.append(f"{eid}: action too thin to be useful: {a!r}")

    for field in ("date", "verified"):
        try:
            datetime.strptime(entry.get(field, ""), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            errs.append(f"{eid}: {field} must be YYYY-MM-DD, got {entry.get(field)!r}")

    try:
        if datetime.strptime(entry.get("verified", ""), "%Y-%m-%d").date() > today:
            errs.append(f"{eid}: verified date is in the future")
    except (ValueError, TypeError):
        pass

    src = entry.get("source") or {}
    for key in ("label", "url"):
        if not src.get(key):
            errs.append(f"{eid}: source needs a {key}")

    ai = entry.get("applies_if") or {}
    for key, allowed in (("markets", JURISDICTIONS), ("products", PRODUCTS),
                         ("sizes", SIZES), ("roles", ROLES)):
        vals = ai.get(key)
        if not isinstance(vals, list) or not vals:
            errs.append(f"{eid}: applies_if.{key} must be a non-empty list")
            continue
        bad = set(vals) - allowed
        if bad:
            errs.append(f"{eid}: applies_if.{key} has unknown values {sorted(bad)}")

    if len(entry.get("summary", "")) > 400:
        errs.append(f"{eid}: summary is {len(entry['summary'])} chars, keep it under 400")

    return errs


def load(today: date) -> tuple[dict, list[str], list[str]]:
    doc = json.loads(DATA.read_text(encoding="utf-8"))
    entries = doc.get("deadlines", [])
    errors: list[str] = []
    warnings: list[str] = []

    seen: set[str] = set()
    slugs: set[str] = set()
    for i, e in enumerate(entries):
        errors.extend(check(e, i, today))
        eid = e.get("id", "")
        if eid in seen:
            errors.append(f"duplicate id {eid!r}")
        seen.add(eid)
        slug = e.get("slug", "")
        if slug in slugs:
            errors.append(f"duplicate slug {slug!r}")
        slugs.add(slug)

        try:
            verified = datetime.strptime(e.get("verified", ""), "%Y-%m-%d").date()
            age = (today - verified).days
            if age > STALE_DAYS:
                warnings.append(f"{eid}: last verified {age} days ago")
        except (ValueError, TypeError):
            pass

    return doc, errors, warnings


def enrich(doc: dict, today: date) -> dict:
    out = dict(doc)
    rows = []
    for e in doc["deadlines"]:
        d = datetime.strptime(e["date"], "%Y-%m-%d").date()
        row = dict(e)
        row["days"] = (d - today).days
        row["status"] = "upcoming" if row["days"] > 0 else "live"
        rows.append(row)
    rows.sort(key=lambda r: (r["days"] < 0, abs(r["days"]) if r["days"] < 0 else r["days"]))
    out["deadlines"] = rows
    out["built"] = today.isoformat()
    return out


# --------------------------------------------------------------------------
# rendering helpers
# --------------------------------------------------------------------------

def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def long_date(iso: str) -> str:
    d = datetime.strptime(iso, "%Y-%m-%d").date()
    return f"{d.day} {d.strftime('%B %Y')}"


def when_phrase(days: int) -> str:
    if days == 0:
        return "Today"
    if days > 0:
        if days == 1:
            return "Tomorrow"
        if days < 60:
            return f"In {days} days"
        return f"In {round(days / 30)} months"
    n = abs(days)
    if n < 60:
        return f"In force for {n} days"
    if n < 730:
        return f"In force for {round(n / 30)} months"
    return f"In force for {n / 365:.1f} years"


def app_hash(entry: dict) -> str:
    ai = entry["applies_if"]
    return f"#m={ai['markets'][0]}&p={ai['products'][0]}"


def tag_list(values, labels) -> str:
    return "".join(f'<span class="tag">{esc(labels.get(v, v))}</span>' for v in values)


def ics(rows: list[dict]) -> str:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//Docket//compliance deadlines//EN", "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH", "X-WR-CALNAME:Docket compliance deadlines",
        f"X-WR-CALDESC:{len(rows)} dated compliance obligations across the EU, India and California",
    ]
    for e in rows:
        start = e["date"].replace("-", "")
        end = (date.fromisoformat(e["date"])).toordinal() + 1
        end_s = date.fromordinal(end).strftime("%Y%m%d")

        def clean(s: str) -> str:
            return (str(s).replace("\\", "\\\\").replace(";", "\\;")
                    .replace(",", "\\,").replace("\n", "\\n"))

        desc = (e["summary"] + "\n\nPenalty: " + (e.get("penalty") or "—")
                + "\n\n" + e["source"]["label"] + "\n" + e["source"]["url"]
                + f"\n\nMore: {SITE}/regime/{e['slug']}.html")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{e['id']}@docket",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{start}",
            f"DTEND;VALUE=DATE:{end_s}",
            f"SUMMARY:{clean(e['regime'] + ' — ' + e['title'])}",
            f"DESCRIPTION:{clean(desc)}",
            f"URL:{SITE}/regime/{e['slug']}.html",
            "TRANSP:TRANSPARENT",
            "BEGIN:VALARM", "TRIGGER:-P14D", "ACTION:DISPLAY",
            f"DESCRIPTION:{clean('Two weeks: ' + e['title'])}", "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


def jsonld(entry: dict, url: str) -> str:
    d = datetime.strptime(entry["date"], "%Y-%m-%d").date()
    payload = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": f"{entry['regime']}: {entry['title']}",
        "description": entry["summary"],
        "datePublished": entry["verified"],
        "dateModified": entry["verified"],
        "inLanguage": "en",
        "isAccessibleForFree": True,
        "url": url,
        "mainEntity": {
            "@type": "Legislation",
            "name": entry["source"]["label"],
            "legislationIdentifier": entry["source"]["label"],
            "url": entry["source"]["url"],
        },
        "about": {
            "@type": "Event",
            "name": entry["title"],
            "startDate": d.isoformat(),
            "eventStatus": "https://schema.org/EventScheduled",
        },
        "publisher": {"@type": "Organization", "name": "Docket", "url": SITE},
    }
    return json.dumps(payload, ensure_ascii=False)


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------

def build_index(data: dict, css: str) -> str:
    tpl = TEMPLATE.read_text(encoding="utf-8")
    if "/*__DOCKET_DATA__*/" not in tpl:
        raise SystemExit("template is missing the /*__DOCKET_DATA__*/ placeholder")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    out = (tpl.replace("/*__DOCKET_DATA__*/", payload)
              .replace("{{CSS}}", css)
              .replace("{{N}}", str(len(data["deadlines"]))))
    if "{{" in out:
        raise SystemExit("index template has an unfilled placeholder")
    return out


def build_regime(entry: dict, rows: list[dict], css: str, today: date) -> str:
    tpl = REGIME_TPL.read_text(encoding="utf-8")
    d = datetime.strptime(entry["date"], "%Y-%m-%d").date()
    days = (d - today).days
    status = "upcoming" if days > 0 else "live"
    url = f"{SITE}/regime/{entry['slug']}.html"

    # Keep the headline readable but let it carry the regime name for search.
    headline = entry["title"]
    if entry["regime"].lower() not in headline.lower():
        headline = f"{entry['regime']}: {headline}"

    # The date is the search term people actually use, so it survives at the
    # expense of the headline. Truncating the headline and keeping the date is
    # the right way round; the old code did the opposite and cut the date off
    # every regime page with a long name.
    stamp = f" — {long_date(entry['date'])} | Docket"
    budget = 70 - len(stamp)
    if budget < 25:
        stamp = f" — {long_date(entry['date'])}"
        budget = 70 - len(stamp)
    short = headline if len(headline) <= budget else headline[:budget - 1].rstrip(" —-:") + "…"
    title = short + stamp

    meta = (f"{entry['summary']} Applies from {long_date(entry['date'])}. "
            f"Source: {entry['source']['label']}.")[:300]

    penalty_block = ""
    if entry.get("penalty"):
        penalty_block = (
            '<p class="penalty" style="margin:24px 0 0"><b>Penalty: </b>'
            + esc(entry["penalty"]) + "</p>"
        )

    warn = ""
    if entry["confidence"] == "reported":
        warn = ('<p class="warn">The date on this page came from a secondary source; '
                'the instrument itself was not read line by line. Confirm before '
                'building a programme on it.</p>')

    ai = entry["applies_if"]
    tags = tag_list(ai["markets"], JURIS_LABEL)
    tags += tag_list(ai["products"], PRODUCT_LABEL)
    tags += tag_list(ai["sizes"], SIZE_LABEL)
    tags += tag_list(ai["roles"], ROLE_LABEL)

    actions = "".join(f"<li>{esc(a)}</li>" for a in entry["actions"])

    related = [
        r for r in rows
        if r["id"] != entry["id"]
        and (set(r["applies_if"]["markets"]) & set(ai["markets"]))
    ]
    related.sort(key=lambda r: (r["days"] < 0, abs(r["days"])))
    related_html = "".join(
        f'<a href="{r["slug"]}.html">{esc(r["regime"])} — {esc(r["title"])}'
        f'<small>{long_date(r["date"])} · {esc(when_phrase(r["days"]))}</small></a>'
        for r in related[:6]
    )

    repl = {
        "{{CSS}}": css,
        "{{TITLE}}": esc(title),
        "{{META}}": esc(meta),
        "{{CANONICAL}}": url,
        "{{JSONLD}}": jsonld(entry, url),
        "{{JURISDICTION}}": esc(JURIS_LABEL.get(entry["jurisdiction"], entry["jurisdiction"])),
        "{{REGIME}}": esc(entry["regime"]),
        "{{HEADLINE}}": esc(headline),
        "{{DATE}}": esc(long_date(entry["date"])),
        "{{STATUS}}": status,
        "{{WHEN}}": esc(when_phrase(days)),
        "{{VERIFIED}}": esc(long_date(entry["verified"])),
        "{{SUMMARY}}": esc(entry["summary"]),
        "{{PENALTY_BLOCK}}": penalty_block,
        "{{APPLIES}}": tags,
        "{{ACTIONS}}": actions,
        "{{SOURCE_URL}}": esc(entry["source"]["url"]),
        "{{SOURCE_LABEL}}": esc(entry["source"]["label"]),
        "{{CONFIDENCE}}": entry["confidence"],
        "{{CONFIDENCE_LABEL}}": ("primary source" if entry["confidence"] == "primary"
                                 else "reported"),
        "{{WARN}}": warn,
        "{{APP_HASH}}": esc(app_hash(entry)),
        "{{RELATED}}": related_html,
    }
    out = tpl
    for k, v in repl.items():
        out = out.replace(k, v)
    leftover = out.count("{{")
    if leftover:
        raise SystemExit(f"{entry['id']}: {leftover} unfilled placeholder(s)")
    return out


def build_changes(changes: dict, css: str) -> str:
    rows = sorted(changes["changes"], key=lambda c: c["date_noticed"], reverse=True)
    items = []
    for c in rows:
        items.append(f"""
      <article class="change">
        <p class="when">{esc(long_date(c['date_noticed']))} · {esc(c['regime'])}</p>
        <h2>{esc(c['what'])}</h2>
        <div class="move"><s>{esc(c['moved_from'])}</s> <span class="arr">→</span> <b>{esc(c['moved_to'])}</b></div>
        <p>{esc(c['why'])}</p>
        <p class="consequence"><b>What it means:</b> {esc(c['consequence'])}</p>
        <p class="src"><a href="{esc(c['source']['url'])}" target="_blank" rel="noopener noreferrer">{esc(c['source']['label'])}</a></p>
      </article>""")
    body = "".join(items)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Compliance deadlines that moved — and what it means | Docket</title>
<meta name="description" content="Every compliance date on Docket that changed after publication, with the instrument that moved it. The AI Act high-risk deadline moved from 2 August 2026 to 2 December 2027.">
<link rel="canonical" href="{SITE}/changes.html">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='7' fill='%23151311'/><path d='M11 8h10M16 8v10M16 18l-4 7M16 18l4 7' stroke='%23f0a020' stroke-width='2.2' stroke-linecap='round' fill='none'/></svg>">
<style>
{css}
  .change {{ border-left: 3px solid var(--accent); padding: 4px 0 4px 20px; margin: 0 0 34px; }}
  .change .when {{ font-family: var(--mono); font-size: 12px; color: var(--ink-3); margin: 0 0 6px; letter-spacing: .04em; }}
  .change h2 {{ font-size: 19px; margin: 0 0 10px; letter-spacing: -.01em; }}
  .change p {{ font-size: 14.5px; color: var(--ink-2); margin: 0 0 10px; max-width: 740px; }}
  .move {{ font-family: var(--mono); font-size: 14px; margin: 0 0 14px; padding: 10px 14px; background: var(--accent-soft); border-radius: 8px; display: inline-block; }}
  .move s {{ color: var(--ink-3); }}
  .move .arr {{ color: var(--accent); margin: 0 4px; }}
  .move b {{ color: var(--ink); }}
  .consequence {{ border-left: 2px solid var(--line); padding-left: 12px; }}
  .consequence b {{ color: var(--ink); }}
  .src a {{ color: var(--ink-3); font-size: 13px; border-bottom: 1px dotted var(--ink-3); text-decoration: none; }}
  .src a:hover {{ color: var(--accent); border-color: var(--accent); }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <p class="crumb" style="font-size:13px;margin:0 0 6px;color:var(--ink-3)">
      <a href="./" style="color:var(--ink-3);text-decoration:none;border-bottom:1px dotted var(--ink-3)">Docket</a>
    </p>
    <h1>What moved, and when</h1>
    <p class="lede">
      A deadline tracker is only worth reading if somebody re-reads the instrument.
      These are the dates that changed after they were published, with the
      instrument that changed them — and what it means for anyone who planned
      around the old date.
    </p>
  </header>
  <div style="margin-top:44px">{body}</div>
  <footer>
    <h2>About this list</h2>
    <p>This is not an automated diff of the dataset and does not claim to be a
    complete history. It records the movements that were verified against a named
    instrument. Absence of an entry means no movement was recorded — not that no
    movement occurred.</p>
    <p><a href="./">Back to Docket</a> · <a href="https://github.com/chirag120670598-dotcom/docket">source</a></p>
  </footer>
</div>
</body>
</html>
"""


def build_sitemap(rows: list[dict], today: date) -> str:
    urls = [(f"{SITE}/", today.isoformat(), "1.0"),
            (f"{SITE}/changes.html", today.isoformat(), "0.9")]
    for r in rows:
        urls.append((f"{SITE}/regime/{r['slug']}.html", r["verified"], "0.8"))
    body = "".join(
        f"  <url><loc>{u}</loc><lastmod>{m}</lastmod><priority>{p}</priority></url>\n"
        for u, m, p in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + body + "</urlset>\n")


# --------------------------------------------------------------------------

def build(check_only: bool = False) -> int:
    today = date.today()
    doc, errors, warnings = load(today)

    print(f"docket · {len(doc.get('deadlines', []))} deadlines · built {today}")
    for w in warnings:
        print(f"  warn  {w}")
    for e in errors:
        print(f"  ERROR {e}")
    if errors:
        print(f"\n{len(errors)} problem(s) — refusing to build.")
        return 1
    if check_only:
        print("dataset is valid")
        return 0

    data = enrich(doc, today)
    rows = data["deadlines"]
    css = STYLE.read_text(encoding="utf-8")
    changes = json.loads(CHANGES.read_text(encoding="utf-8"))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "regime").mkdir(exist_ok=True)

    index_html = build_index(data, css)
    (OUT / "index.html").write_text(index_html, encoding="utf-8")

    for r in rows:
        page = build_regime(r, rows, css, today)
        (OUT / "regime" / f"{r['slug']}.html").write_text(page, encoding="utf-8")

    (OUT / "changes.html").write_text(build_changes(changes, css), encoding="utf-8")

    feed = ics(rows)
    (OUT / "deadlines.ics").write_text(feed, encoding="utf-8", newline="")

    (OUT / "sitemap.xml").write_text(build_sitemap(rows, today), encoding="utf-8")
    (OUT / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n\n"
        f"Sitemap: {SITE}/sitemap.xml\n", encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    upcoming = sum(1 for r in rows if r["status"] == "upcoming")
    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"wrote {len(rows) + 4} files to site/ — "
          f"{total / 1024:.0f} KB, {upcoming} upcoming, {len(rows) - upcoming} in force")
    print(f"  index.html {len(index_html) / 1024:.1f} KB · "
          f"{len(rows)} regime pages · changes.html · deadlines.ics "
          f"({len(feed) / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate only")
    sys.exit(build(ap.parse_args().check))

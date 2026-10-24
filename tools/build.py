#!/usr/bin/env python3
"""Validate the deadline dataset and build the static site.

Two jobs:

1. **Validate.** Every entry must name its instrument, carry a verification date,
   and use a vocabulary the site actually understands. A deadline page that
   quietly drifts out of date is worse than no deadline page, because people make
   decisions on it.

2. **Build.** Inject the dataset into the HTML template so the site is a single
   file with no fetch, no CORS and no build server. It opens from a USB stick and
   it deploys to any static host.

Run:  python3 tools/build.py
Check only (exit 1 on problems):  python3 tools/build.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docket" / "data" / "deadlines.json"
TEMPLATE = ROOT / "web" / "template.html"
OUT = ROOT / "site" / "index.html"

JURISDICTIONS = {"EU", "IN", "US-CA", "UK", "GLOBAL"}
PRODUCTS = {"connected_device", "software", "ai_system", "physical_goods", "services"}
SIZES = {"micro", "small", "medium", "large"}
ROLES = {"manufacturer", "importer", "distributor", "provider", "deployer", "employer"}
KINDS = {"obligation", "deadline", "repeal"}
CONFIDENCE = {"primary", "reported"}

# An entry older than this has not been re-checked and is flagged in the build
# output. It still ships — hiding it would help nobody — but it is visible.
STALE_DAYS = 120


class Problem(str):
    pass


def check(entry: dict, idx: int, today: date) -> list[str]:
    errs: list[str] = []
    eid = entry.get("id", f"#{idx}")

    for key in ("id", "jurisdiction", "regime", "title", "date", "kind",
                "summary", "source", "confidence", "verified", "applies_if"):
        if not entry.get(key):
            errs.append(f"{eid}: missing required field {key!r}")

    if entry.get("jurisdiction") not in JURISDICTIONS:
        errs.append(f"{eid}: unknown jurisdiction {entry.get('jurisdiction')!r}")
    if entry.get("kind") not in KINDS:
        errs.append(f"{eid}: unknown kind {entry.get('kind')!r}")
    if entry.get("confidence") not in CONFIDENCE:
        errs.append(f"{eid}: confidence must be one of {sorted(CONFIDENCE)}")

    for field, allowed in (("date", None), ("verified", None)):
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
    for i, e in enumerate(entries):
        errors.extend(check(e, i, today))
        eid = e.get("id", "")
        if eid in seen:
            errors.append(f"duplicate id {eid!r}")
        seen.add(eid)

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
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    tpl = TEMPLATE.read_text(encoding="utf-8")
    if "/*__DOCKET_DATA__*/" not in tpl:
        print("template is missing the /*__DOCKET_DATA__*/ placeholder")
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    html = tpl.replace("/*__DOCKET_DATA__*/", payload)
    OUT.write_text(html, encoding="utf-8")

    upcoming = sum(1 for r in data["deadlines"] if r["status"] == "upcoming")
    print(f"wrote {OUT.relative_to(ROOT)} — {len(html) / 1024:.1f} KB, "
          f"{upcoming} upcoming, {len(data['deadlines']) - upcoming} in force")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate only")
    sys.exit(build(ap.parse_args().check))

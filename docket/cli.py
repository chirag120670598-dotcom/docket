"""Command line for Docket.

    docket deadlines --market EU --product software --size small
    docket clock --path vulnerability --aware "3h ago" --fix "2d"
    docket route --main-establishment DE
    docket dossier --path vulnerability --stage notification
    docket check
    docket export --format ics
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path as FsPath

from . import __version__
from .dossier import (
    REQUIREMENTS,
    SEVERE_TEST,
    Draft,
    Path,
    Stage,
    example_dossier,
    schedule,
)
from .routing import MEMBER_STATES, route

ROOT = FsPath(__file__).resolve().parent.parent
DATA = FsPath(__file__).parent / "data" / "deadlines.json"

KINDS = {"obligation", "deadline", "repeal"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def load_deadlines() -> list[dict]:
    if not DATA.exists():
        sys.exit(f"dataset not found at {DATA}")
    return json.loads(DATA.read_text(encoding="utf-8"))["deadlines"]


def parse_when(text: str) -> datetime:
    """'3h ago', '2d', 'now', '2026-11-02T09:00Z'. Same vocabulary as hourglass."""
    t = text.strip().lower()
    now = datetime.now(timezone.utc)
    if t in ("now", "just now", "0"):
        return now
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(m|min|mins|h|hr|hrs|d|day|days)\s*(ago|from now|ahead)?", t)
    if m:
        n = float(m.group(1))
        unit = m.group(2)[0]
        delta = timedelta(minutes=n) if unit == "m" else (
            timedelta(hours=n) if unit == "h" else timedelta(days=n))
        return now - delta if (m.group(3) in (None, "ago")) else now + delta
    try:
        s = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        sys.exit(f"cannot read a time from {text!r} — try '3h ago', '2d', or an ISO timestamp")


def roles_for(products: set[str]) -> set[str]:
    r = {"employer"}
    if products & {"connected_device", "physical_goods"}:
        r |= {"manufacturer", "importer"}
    if products & {"software", "ai_system"}:
        r |= {"provider", "manufacturer"}
    if "services" in products:
        r.add("provider")
    if "ai_system" in products:
        r.add("deployer")
    return r


def matches(entry: dict, markets: set[str], products: set[str],
            size: str | None) -> bool:
    a = entry["applies_if"]
    if not set(a["markets"]) & markets:
        return False
    if not set(a["products"]) & products:
        return False
    if size and size not in a["sizes"]:
        return False
    return bool(set(a["roles"]) & roles_for(products))


def human_days(n: int) -> str:
    if n == 0:
        return "today"
    if n > 0:
        return f"in {n}d"
    m = -n
    if m < 60:
        return f"{m}d ago"
    if m < 730:
        return f"{round(m / 30)}mo ago"
    return f"{m / 365:.1f}y ago"


def ics(entries: list[dict]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//Docket//compliance deadlines//EN", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:Docket compliance deadlines"]
    for e in entries:
        start = e["date"].replace("-", "")
        end = (date.fromisoformat(e["date"]) + timedelta(days=1)).strftime("%Y%m%d")
        desc = (e["summary"] + "\\n\\nPenalty: " + e.get("penalty", "-")
                + "\\nSource: " + e["source"]["label"] + " " + e["source"]["url"])
        desc = desc.replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")
        lines += ["BEGIN:VEVENT", f"UID:{e['id']}@docket", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{start}", f"DTEND;VALUE=DATE:{end}",
                  f"SUMMARY:{e['regime']} — {e['title']}".replace(",", "\\,"),
                  f"DESCRIPTION:{desc}", "TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_deadlines(a) -> int:
    entries = load_deadlines()
    markets = set(a.market or [])
    products = set(a.product or [])
    if not markets or not products:
        sys.exit("give at least one --market and one --product (see --help)")

    hits = [e for e in entries if matches(e, markets, products, a.size)]
    today = date.today()
    for e in hits:
        e["_days"] = (date.fromisoformat(e["date"]) - today).days
    hits.sort(key=lambda e: (e["_days"] < 0, e["_days"] if e["_days"] > 0 else -e["_days"]))

    if a.json:
        print(json.dumps([{k: v for k, v in e.items() if k != "_days"}
                          for e in hits], indent=2, ensure_ascii=False))
        return 0

    if not hits:
        print("No deadline in the dataset matches those answers.")
        print("That is a real answer, but it may also mean a regime is missing.")
        return 0

    print(f"{len(hits)} deadline(s) apply\n")
    for e in hits:
        state = "UPCOMING" if e["_days"] > 0 else "IN FORCE"
        print(f"  {state:9} {human_days(e['_days']):>9}  {e['date']}  {e['regime']}")
        print(f"  {'':9} {'':>9}  {e['title']}")
        print(f"  {'':9} {'':>9}  {e['source']['label']}")
        if e.get("penalty"):
            p = e["penalty"]
            print(f"  {'':9} {'':>9}  Penalty: {p[:110]}{'…' if len(p) > 110 else ''}")
        print()
    return 0


def cmd_clock(a) -> int:
    aware = parse_when(a.aware)
    path = Path(a.path)
    fix = parse_when(a.fix) if a.fix else None
    sent = parse_when(a.sent) if a.sent else None

    clocks = schedule(path, aware, fix_available_at=fix, notification_sent_at=sent)
    no_fix = path is Path.VULNERABILITY and fix is None

    if a.json:
        # One envelope, always the same shape. Wrapping only when there is a
        # note would give callers two output formats to defend against.
        payload = {
            "path": path.value,
            "aware_at": aware.isoformat(),
            "clocks": [{
                "stage": c.stage.value,
                "due": c.due.isoformat(),
                "hours_left": round(c.hours_left, 2),
                "overdue": c.is_overdue,
                "basis": c.basis,
            } for c in clocks],
        }
        if no_fix:
            payload["note"] = (
                "no fix was supplied, so the final report has no date yet; "
                "Article 14(2)(c) runs from the moment a corrective or "
                "mitigating measure is available")
        print(json.dumps(payload, indent=2))
        return 0

    if no_fix:
        print("note: no --fix given, so the final report has no date yet.")
        print("      Article 14(2)(c) runs from the moment a corrective or")
        print("      mitigating measure is available, not from the fix's release.\n")

    print(f"{a.path} path · aware at {aware.isoformat(timespec='minutes')}\n")
    for c in clocks:
        print(f"  {c.stage.value.replace('_', ' '):14} {c.due.strftime('%Y-%m-%d %H:%M UTC')}"
              f"   {c.human():>22}")
        print(f"  {'':14} {c.basis}")
    return 0


def cmd_route(a) -> int:
    def pair(code, count):
        return (code, count) if code else None

    def headcounts(items):
        out = {}
        for item in items:
            if "=" not in item:
                sys.exit(f"--employees expects CODE=COUNT, got {item!r}")
            code, _, raw = item.partition("=")
            try:
                out[code.strip()] = int(raw)
            except ValueError:
                sys.exit(f"--employees count must be a whole number, got {raw!r}")
        return out

    try:
        r = route(
            main_establishment=a.main_establishment,
            employees_by_state=headcounts(a.employees) if a.employees else None,
            has_eu_establishment=not a.no_eu_establishment,
            representative=pair(a.representative, a.representative_count),
            importer=pair(a.importer, a.importer_count),
            distributor=pair(a.distributor, a.distributor_count),
            users=pair(a.users, a.users_count),
        )
    except ValueError as exc:
        sys.exit(f"invalid Member State: {exc}. "
                 f"Use a two-letter code such as DE, FR, IE, PL.")
    if a.json:
        print(json.dumps({
            "resolved": r.resolved, "state": r.state,
            "state_name": r.state_name, "branch": r.branch,
            "reason": r.reason, "missing": r.missing, "sticky": r.sticky,
        }, indent=2))
        return 0
    print(r.explain())
    return 0 if r.resolved else 2


def cmd_dossier(a) -> int:
    if a.path and a.stage:
        d = Draft(path=Path(a.path), stage=Stage(a.stage),
                  product=a.product or "(product not supplied)",
                  manufacturer=a.manufacturer or "(manufacturer not supplied)",
                  facts=dict(x.split("=", 1) for x in a.field) if a.field else {})
    else:
        d = example_dossier()

    if a.markdown:
        print(d.as_markdown())
    else:
        print(d.as_text())
    return 0


def cmd_requirements(a) -> int:
    for (path, stage), reqs in REQUIREMENTS.items():
        print(f"\n{path.value} · {stage.value}")
        for r in reqs:
            print(f"  - {r.describe()}")
    print("\nSevere incident test (Article 14(5)) — either limb is enough:")
    for _, text in SEVERE_TEST:
        print(f"  - {text}")
    return 0


def cmd_check(a) -> int:
    entries = load_deadlines()
    problems = []
    seen = set()
    today = date.today()
    for e in entries:
        eid = e.get("id", "?")
        if eid in seen:
            problems.append(f"{eid}: duplicate id")
        seen.add(eid)
        for k in ("id", "jurisdiction", "regime", "title", "date", "kind",
                  "summary", "source", "confidence", "verified", "applies_if"):
            if not e.get(k):
                problems.append(f"{eid}: missing {k}")
        try:
            d = date.fromisoformat(e["date"])
            v = date.fromisoformat(e["verified"])
            if v > today:
                problems.append(f"{eid}: verified in the future")
            if (today - v).days > 365:
                problems.append(f"{eid}: not verified in over a year")
            if d.year < 2015:
                problems.append(f"{eid}: date looks wrong ({d})")
        except (ValueError, KeyError):
            problems.append(f"{eid}: bad date")
        url = (e.get("source") or {}).get("url", "")
        if not url.startswith("http"):
            problems.append(f"{eid}: source url missing")

    print(f"{len(entries)} deadlines checked")
    for p in problems:
        print(f"  ✗ {p}")
    if not problems:
        print("  ✓ no problems found")
    return 1 if problems else 0


def cmd_export(a) -> int:
    entries = load_deadlines()
    if a.market or a.product:
        entries = [e for e in entries
                   if matches(e, set(a.market or ["EU", "IN", "US-CA"]),
                              set(a.product or ["software"]), a.size)]
    if a.format == "ics":
        sys.stdout.write(ics(entries))
    elif a.format == "md":
        print("| Date | Regime | What | Source |")
        print("|---|---|---|---|")
        for e in sorted(entries, key=lambda x: x["date"]):
            print(f"| {e['date']} | {e['regime']} | {e['title']} | {e['source']['url']} |")
    else:
        print(json.dumps(entries, indent=2, ensure_ascii=False))
    return 0


# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="docket",
        description="Compliance deadlines that apply to you, and the CRA "
                    "Article 14 clock.",
        epilog="Zero dependencies. Dataset in data/deadlines.json.")
    ap.add_argument("--version", action="version", version=f"docket {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("deadlines", help="which deadlines bind a given company")
    p.add_argument("--market", action="append", choices=["EU", "IN", "US-CA", "UK", "GLOBAL"])
    p.add_argument("--product", action="append",
                   choices=["connected_device", "software", "ai_system",
                            "physical_goods", "services"])
    p.add_argument("--size", choices=["micro", "small", "medium", "large"])
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_deadlines)

    p = sub.add_parser("clock", help="the three Article 14 clocks")
    p.add_argument("--path", required=True, choices=[x.value for x in Path])
    p.add_argument("--aware", required=True, help="e.g. '3h ago', '2026-11-02T09:00Z'")
    p.add_argument("--fix", help="when a corrective measure became available")
    p.add_argument("--sent", help="when the notification was actually submitted")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_clock)

    p = sub.add_parser("route", help="which CSIRT, per Article 14(7)")
    p.add_argument("--main-establishment")
    p.add_argument("--employees", action="append", metavar="DE=120")
    p.add_argument("--no-eu-establishment", action="store_true")
    p.add_argument("--representative")
    p.add_argument("--representative-count", type=int, default=0)
    p.add_argument("--importer")
    p.add_argument("--importer-count", type=int, default=0)
    p.add_argument("--distributor")
    p.add_argument("--distributor-count", type=int, default=0)
    p.add_argument("--users")
    p.add_argument("--users-count", type=int, default=0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_route)

    p = sub.add_parser("dossier", help="build a filing against Article 14's field list")
    p.add_argument("--path", choices=[x.value for x in Path])
    p.add_argument("--stage", choices=[x.value for x in Stage])
    p.add_argument("--product")
    p.add_argument("--manufacturer")
    p.add_argument("--field", action="append", metavar="key=value")
    p.add_argument("--markdown", action="store_true")
    p.set_defaults(fn=cmd_dossier)

    p = sub.add_parser("requirements", help="print the field lists")
    p.set_defaults(fn=cmd_requirements)

    p = sub.add_parser("check", help="validate the dataset")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("export", help="export deadlines as ics/md/json")
    p.add_argument("--format", choices=["ics", "md", "json"], default="ics")
    p.add_argument("--market", action="append")
    p.add_argument("--product", action="append")
    p.add_argument("--size")
    p.set_defaults(fn=cmd_export)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

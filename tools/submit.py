#!/usr/bin/env python3
"""Tell search engines that the pages exist. No account, no cost.

Almost every "submit your site" route needs an account and a verification step,
which is exactly the kind of thing a project with no budget cannot do. IndexNow
is the exception: you host a text file containing a key at the domain root, and
then you may push URLs to the endpoint. Bing and Yandex use it, and a
participating engine shares the submission with the others.

    python3 tools/submit.py            # submit every page in the sitemap
    python3 tools/submit.py --dry-run  # print what would be sent

Google does not participate in IndexNow. Nothing here replaces Search Console;
it just means the site is not invisible until somebody remembers to sign up for
it. Being straight about that matters more than a larger number in the summary.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
SITEMAP = SITE / "sitemap.xml"

ENDPOINTS = [
    "https://api.indexnow.org/indexnow",
    "https://www.bing.com/indexnow",
]


def sitemap_urls() -> list[str]:
    text = SITEMAP.read_text(encoding="utf-8")
    return re.findall(r"<loc>(.*?)</loc>", text)


def find_key() -> tuple[str, str] | None:
    """The key file is written by the build, so pick it up from the output."""
    for f in SITE.glob("*.txt"):
        if f.name == "robots.txt":
            continue
        body = f.read_text(encoding="utf-8").strip()
        if f.stem == body and len(body) >= 8:
            return f.stem, body
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not SITEMAP.exists():
        print("no sitemap — run tools/build.py first")
        return 1

    found = find_key()
    if not found:
        print("no IndexNow key file in site/ — run tools/build.py first")
        return 1
    key, body = found

    urls = sitemap_urls()
    host = re.sub(r"^https?://", "", urls[0]).split("/")[0]
    payload = {
        "host": host,
        "key": body,
        "keyLocation": f"https://{host}/{key}.txt",
        "urlList": urls,
    }

    print(f"indexnow · {len(urls)} urls · host {host} · key {key}")
    if args.dry_run:
        print(json.dumps(payload, indent=2)[:800])
        return 0

    ok = 0
    for endpoint in ENDPOINTS:
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8",
                     "User-Agent": "docket-indexnow/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                print(f"  {endpoint} -> {resp.status}")
                ok += 1
        except urllib.error.HTTPError as e:
            # 202 means accepted; some engines answer 200. Anything else is a
            # real failure and should be visible rather than swallowed.
            print(f"  {endpoint} -> HTTP {e.code} {e.reason}")
        except Exception as e:  # noqa: BLE001 - report, never crash the build
            print(f"  {endpoint} -> {type(e).__name__}: {e}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

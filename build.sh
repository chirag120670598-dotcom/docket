#!/bin/sh
# Build the site. Vercel's build image has python3; some CI images only have
# `python`, so try both rather than failing the deploy over a binary name.
set -e
if command -v python3 >/dev/null 2>&1; then
  exec python3 tools/build.py
elif command -v python >/dev/null 2>&1; then
  exec python tools/build.py
else
  echo "no python interpreter found" >&2
  exit 1
fi

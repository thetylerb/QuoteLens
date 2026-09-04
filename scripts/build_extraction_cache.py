#!/usr/bin/env python3
"""
Runs every scenario in examples/scenarios.txt through Claude once and writes
data/extraction_cache.json. Resumable — a scenario already in the cache is
skipped, so re-running after an interruption only fills in what's missing.

Usage:
    python scripts/build_extraction_cache.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if _stream.encoding is not None and _stream.encoding.lower() != "utf-8":
        _stream.reconfigure(encoding="utf-8")

# Bootstrap sys.path with this script's own location (unavoidable — nothing
# else can tell us where the package lives yet), then hand off to
# engine.extraction.PROJECT_ROOT as the single canonical root for every path
# below. Neither this file's directory nor the current working directory is
# used again after this point.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import extraction

PROJECT_ROOT = extraction.PROJECT_ROOT
SCENARIOS_PATH = PROJECT_ROOT / "examples" / "scenarios.txt"


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set — nothing to build (there's no live call to cache).", file=sys.stderr)
        sys.exit(1)

    scenarios = [line.strip() for line in SCENARIOS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]

    extraction.CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    api_key = os.environ["ANTHROPIC_API_KEY"]
    failures = 0

    for i, text in enumerate(scenarios, start=1):
        key = extraction._hash_text(text)
        if extraction._cache_lookup(key) is not None:
            print(f"[{i}/{len(scenarios)}] already cached — skipping: {text[:60]!r}")
            continue

        print(f"[{i}/{len(scenarios)}] live call: {text[:60]!r}")
        try:
            payload = extraction._extract_live(text, api_key)
        except Exception as exc:
            failures += 1
            print(f"    -> FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue

        extraction._cache_store(key, payload)
        result = extraction._build_result(payload, source="live")
        print(f"    -> source=live confidence={result.confidence:.2f}")

    cache_path = extraction.CACHE_PATH.resolve()
    entry_count = len(json.loads(cache_path.read_text(encoding="utf-8"))) if cache_path.exists() else 0
    print(f"Cache path: {cache_path}")
    print(f"Entries: {entry_count}")
    print(f"Failures: {failures}")

    if entry_count == 0:
        print("FATAL: cache has 0 entries — every scenario failed or none were processed.", file=sys.stderr)
        sys.exit(1)
    if failures:
        print(f"FATAL: {failures}/{len(scenarios)} scenario(s) failed to extract live.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

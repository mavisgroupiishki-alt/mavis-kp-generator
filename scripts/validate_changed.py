#!/usr/bin/env python3
"""Validate registry JSON files passed on the command line."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from run_weekly import ROOT, load_json, validate_dataset


def main() -> int:
    config = json.loads((ROOT / "scripts" / "registry_sources.json").read_text(encoding="utf-8"))
    by_path = {str(Path(cfg["output"])): (source, cfg) for source, cfg in config.items()}
    errors = 0
    for raw in sys.argv[1:]:
        relative = str(Path(raw))
        if relative == "data/registry_status.json":
            continue
        mapped = by_path.get(relative)
        if not mapped:
            print(f"SKIP {relative}: not a configured registry output")
            continue
        source, cfg = mapped
        data = load_json(ROOT / relative)
        count = int((data or {}).get("count") or 0)
        ok, messages = validate_dataset(source, data, int(cfg.get("min_count") or 1), 0)
        print(("OK" if ok else "FAIL"), relative, "—", "; ".join(messages) if messages else f"{count} records")
        errors += 0 if ok else 1
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

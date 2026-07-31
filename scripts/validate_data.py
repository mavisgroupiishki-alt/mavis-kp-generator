#!/usr/bin/env python3
"""Проверка уже опубликованных JSON-баз без обращения к реестрам."""

from __future__ import annotations

import json
from pathlib import Path

from run_weekly import ROOT, load_json, validate_dataset


def main() -> int:
    config = json.loads((ROOT / "scripts" / "registry_sources.json").read_text(encoding="utf-8"))
    errors = 0
    for source, cfg in config.items():
        path = ROOT / cfg["output"]
        data = load_json(path)
        if data is None and cfg.get("parser") is None:
            print(f"SKIP {source}: коннектор ещё не реализован")
            continue
        previous_count = int((data or {}).get("count") or 0)
        ok, messages = validate_dataset(source, data, int(cfg.get("min_count") or 1), previous_count)
        print(("OK  " if ok else "FAIL"), source, "—", "; ".join(messages) if messages else f"{previous_count} записей")
        if not ok:
            errors += 1
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

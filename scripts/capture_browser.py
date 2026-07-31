#!/usr/bin/env python3
"""Diagnostic browser capture for JS-heavy registries.

This does not bypass CAPTCHA or access controls. It opens official public pages
in a persistent local Chrome profile and saves HTML plus JSON network responses.
The captures are used to implement stable source-specific connectors for ISO,
metal certificates and licences without relying on a browser extension.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.async_api import Response, async_playwright

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "scripts" / "registry_sources.json").read_text(encoding="utf-8"))
CAPTURE_ROOT = ROOT / "snapshots"
PROFILE_DIR = ROOT / ".browser-profile"


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", value)[:100]


async def capture_source(context: Any, source: str, wait_seconds: int) -> None:
    cfg = CONFIG[source]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = CAPTURE_ROOT / source / stamp
    network_dir = target / "network"
    network_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, Any]] = []
    counter = 0
    page = await context.new_page()

    async def on_response(response: Response) -> None:
        nonlocal counter
        try:
            content_type = (response.headers.get("content-type") or "").lower()
            url_low = response.url.lower()
            if "json" not in content_type and not any(token in url_low for token in ("/api/", "ajax", "registry", "cert", "license")):
                return
            body = await response.body()
            if not body or len(body) > 30_000_000:
                return
            counter += 1
            ext = ".json" if "json" in content_type else ".txt"
            filename = f"{counter:04d}_{safe_name(response.url.split('?')[0].rsplit('/', 1)[-1] or 'response')}{ext}"
            (network_dir / filename).write_bytes(body)
            index.append(
                {
                    "file": filename,
                    "url": response.url,
                    "status": response.status,
                    "content_type": content_type,
                    "bytes": len(body),
                }
            )
        except Exception as exc:
            index.append({"url": response.url, "capture_error": str(exc)})

    page.on("response", on_response)
    print(f"[{source}] open {cfg['url']}")
    try:
        await page.goto(cfg["url"], wait_until="domcontentloaded", timeout=120_000)
        await page.wait_for_timeout(wait_seconds * 1000)
        await page.screenshot(path=str(target / "page.png"), full_page=True)
        (target / "page.html").write_text(await page.content(), encoding="utf-8")
    finally:
        (target / "network_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        await page.close()
    print(f"[{source}] saved to {target.relative_to(ROOT)}; network responses: {len(index)}")


async def async_main(args: argparse.Namespace) -> int:
    selected = args.sources or ["iso", "metal", "lic"]
    unknown = [source for source in selected if source not in CONFIG]
    if unknown:
        raise SystemExit("Unknown sources: " + ", ".join(unknown))

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=args.headless,
            viewport={"width": 1440, "height": 1000},
            locale="ru-RU",
        )
        try:
            for source in selected:
                await capture_source(context, source, args.wait)
        finally:
            await context.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", nargs="*", help="Registry IDs; default: iso metal lic")
    parser.add_argument("--wait", type=int, default=30, help="Seconds to wait for SPA data")
    parser.add_argument("--headless", action="store_true", help="Use headless mode; headed mode is safer for public sites")
    return asyncio.run(async_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

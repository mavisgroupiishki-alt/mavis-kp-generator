"""Парсер действующих аттестатов соответствия юридических лиц.

Источник: https://att.bsc.by/reestr
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://att.bsc.by/reestr"
OUT_FILE = Path("data/att.json")
TIMEOUT = 60
PER_PAGE = 50
MAX_PAGES = 250
PAUSE_BETWEEN_PAGES = 1.0

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}

CERT_RE = re.compile(r"\b(?:BY[\s/.-]*)?\d{5,}(?:[-/.][\dА-ЯA-Z]+)+\b", re.I)


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", value)
    if not match:
        return None
    day, month, year = match.groups()
    return f"{year}-{month.zfill(2)}-{day.zfill(2)}"


def fetch_page(page_num: int) -> str:
    params = {"items_per_page": PER_PAGE}
    if page_num:
        params["page"] = page_num
    response = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
    print(f"[ATT] page={page_num}: HTTP {response.status_code}, {len(response.text)} chars")
    response.raise_for_status()
    return response.text


def is_organization(text: str) -> bool:
    if not text or len(text) < 3:
        return False
    if re.match(r"^(г\.|город|обл\.|область|д\.|ул\.)", text, re.I):
        return False
    if re.search(r"категор|соответствует|не соответствует", text, re.I):
        return False
    if CERT_RE.search(text) or parse_date(text):
        return False
    return bool(re.search(r"[А-ЯЁA-Z]", text, re.I))


def parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records: list[dict] = []

    for row in soup.find_all("tr"):
        cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip() for td in row.find_all("td")]
        if len(cells) < 5:
            continue

        cert_number = next((m.group(0) for cell in cells if (m := CERT_RE.search(cell))), None)
        if not cert_number:
            continue

        organization = cells[0] if is_organization(cells[0]) else next((cell for cell in cells if is_organization(cell)), None)
        if not organization:
            continue

        dates = [date for cell in cells if (date := parse_date(cell))]
        category = next((cell for cell in cells if re.search(r"категор", cell, re.I)), None)
        status = next((cell for cell in reversed(cells) if re.search(r"соответств|действ|приостанов", cell, re.I)), None)
        address = cells[1] if len(cells) > 1 and cells[1] != cert_number and not parse_date(cells[1]) else None
        unp_match = next((re.search(r"\b\d{9}\b", cell) for cell in cells if re.search(r"\b\d{9}\b", cell)), None)

        records.append(
            {
                "cert_number": cert_number,
                "organization": organization,
                "unp": unp_match.group(0) if unp_match else None,
                "address": address,
                "category": category,
                "activity": category,
                "issue_date": dates[0] if dates else None,
                "expiry_date": dates[-1] if len(dates) > 1 else None,
                "status": status,
                "raw_cells": cells,
            }
        )

    return records


def has_next_page(html: str, current_page: int) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    return bool(
        soup.find("a", href=re.compile(rf"[?&]page={current_page + 1}(?:\D|$)"))
        or soup.find(class_=re.compile(r"pager.*next", re.I))
    )


def main() -> None:
    all_records: list[dict] = []
    seen: set[str] = set()

    for page_num in range(MAX_PAGES):
        try:
            html = fetch_page(page_num)
        except Exception as exc:
            print(f"[ATT] Ошибка страницы {page_num}: {exc}", file=sys.stderr)
            if page_num == 0:
                raise
            break

        page_records = parse_page(html)
        added = 0
        for record in page_records:
            key = record["cert_number"] + "|" + record["organization"]
            if key in seen:
                continue
            seen.add(key)
            all_records.append(record)
            added += 1
        print(f"[ATT] page={page_num}: parsed={len(page_records)}, new={added}, total={len(all_records)}")

        if not has_next_page(html, page_num):
            break
        time.sleep(PAUSE_BETWEEN_PAGES)

    if not all_records:
        raise RuntimeError("Не найдено ни одного действующего аттестата; рабочий файл не перезаписан")

    output = {
        "source": "att",
        "source_name": "Аттестаты соответствия юридических лиц",
        "url": BASE_URL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(all_records),
        "records": all_records,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ATT] Saved {len(all_records)} records to {OUT_FILE}")


if __name__ == "__main__":
    main()

"""Парсер старого перечня СПК Белстройцентра.

Источник: https://bsc.by/ru/building/ip
Страница содержит карточки с подписями полей и пагинацию Drupal.
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

BASE_URL = "https://bsc.by/ru/building/ip"
OUT_FILE = Path("data/spk.json")
TIMEOUT = 60
MAX_PAGES = 500
PAUSE_BETWEEN_PAGES = 0.8

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", value)
    if not match:
        return None
    day, month, year = match.groups()
    return f"{year}-{month.zfill(2)}-{day.zfill(2)}"


def fetch_page(page_num: int) -> str:
    params = {"page": page_num} if page_num else {}
    response = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
    print(f"[SPK] page={page_num}: HTTP {response.status_code}, {len(response.text)} chars")
    response.raise_for_status()
    return response.text


def clean_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return [re.sub(r"\s+", " ", line).strip() for line in soup.get_text("\n").splitlines() if line.strip()]


def value_after(lines: list[str], label: str) -> str | None:
    label_low = label.lower()
    for index, line in enumerate(lines):
        low = line.lower()
        if low == label_low and index + 1 < len(lines):
            return lines[index + 1]
        if low.startswith(label_low + " "):
            return line[len(label) :].strip(" :") or None
    return None


def parse_page(html: str) -> list[dict]:
    lines = clean_lines(html)
    starts = [i for i, line in enumerate(lines) if line.lower().startswith("№ свидетельства")]
    records: list[dict] = []

    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else min(len(lines), start + 40)
        block = lines[start:end]
        cert_number = value_after(block, "№ свидетельства")
        organization = value_after(block, "Заявитель")
        evaluator = value_after(block, "Организация по оценке")
        unp = value_after(block, "УНП заявителя")
        address = value_after(block, "Адрес")
        issue_date = parse_date(value_after(block, "Дата выдачи"))
        expiry_date = parse_date(value_after(block, "Действителен до"))
        status = value_after(block, "Статус")

        if not cert_number or not re.search(r"\d{4,}.*[-/.]", cert_number):
            continue
        if not organization:
            continue

        unp_match = re.search(r"\b\d{9}\b", unp or "")
        records.append(
            {
                "cert_number": cert_number,
                "organization": organization,
                "unp": unp_match.group(0) if unp_match else None,
                "evaluator": evaluator,
                "address": address,
                "issue_date": issue_date,
                "expiry_date": expiry_date,
                "status": status,
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
            print(f"[SPK] Ошибка страницы {page_num}: {exc}", file=sys.stderr)
            if page_num == 0:
                raise
            break

        page_records = parse_page(html)
        added = 0
        for record in page_records:
            key = record["cert_number"]
            if key in seen:
                continue
            seen.add(key)
            all_records.append(record)
            added += 1

        print(f"[SPK] page={page_num}: parsed={len(page_records)}, new={added}, total={len(all_records)}")
        if not has_next_page(html, page_num):
            break
        time.sleep(PAUSE_BETWEEN_PAGES)

    if not all_records:
        raise RuntimeError("Не найдено ни одной записи СПК; рабочий файл не перезаписан")

    output = {
        "source": "spk",
        "source_name": "СПК старый (Белстройцентр)",
        "url": BASE_URL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(all_records),
        "records": all_records,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SPK] Saved {len(all_records)} records to {OUT_FILE}")


if __name__ == "__main__":
    main()

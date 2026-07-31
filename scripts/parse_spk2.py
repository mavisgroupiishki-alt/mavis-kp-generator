"""Парсер нового реестра СПК.

Источник: https://spk.bsc.by/cert_register
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

BASE_URL = "https://spk.bsc.by/cert_register"
OUT_FILE = Path("data/spk2.json")
TIMEOUT = 60
PAGE_SIZE = 50
MAX_PAGES = 300
PAUSE_BETWEEN_PAGES = 0.8

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

CERT_RE = re.compile(r"\b\d{5,}(?:[.\-/][\dА-ЯA-Z]+)+\b", re.I)


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", value)
    if not match:
        return None
    day, month, year = match.groups()
    return f"{year}-{month.zfill(2)}-{day.zfill(2)}"


def fetch_page(page_num: int) -> str:
    params = {"pageNumber": page_num, "pageSize": PAGE_SIZE}
    response = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
    print(f"[SPK2] page={page_num}: HTTP {response.status_code}, {len(response.text)} chars")
    response.raise_for_status()
    return response.text


def clean_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return [re.sub(r"\s+", " ", line).strip() for line in soup.get_text("\n").splitlines() if line.strip()]


def value_after(lines: list[str], labels: tuple[str, ...]) -> str | None:
    labels_low = tuple(label.lower() for label in labels)
    for index, line in enumerate(lines):
        low = line.lower().rstrip(":")
        for label, label_low in zip(labels, labels_low):
            if low == label_low and index + 1 < len(lines):
                return lines[index + 1]
            if low.startswith(label_low + " "):
                return line[len(label) :].strip(" :") or None
    return None


def parse_page(html: str) -> list[dict]:
    lines = clean_lines(html)
    marker = "регистрационный номер свидетельства"
    starts = [i for i, line in enumerate(lines) if line.lower().rstrip(":") == marker]
    records: list[dict] = []

    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else min(len(lines), start + 55)
        block = lines[start:end]
        raw_cert = value_after(block, ("Регистрационный номер свидетельства",))
        cert_match = CERT_RE.search(raw_cert or "")
        if not cert_match:
            continue
        cert_number = cert_match.group(0)

        organization = value_after(
            block,
            (
                "Юридическое лицо",
                "Полное наименование юридического лица",
                "Наименование юридического лица",
                "Заявитель",
            ),
        )
        if organization and organization.lower() in {"полное название", "унитарная организация"}:
            organization = None
        if not organization:
            organization = next(
                (
                    line
                    for line in block
                    if re.search(r"\b(ООО|ОАО|ЗАО|УП|ЧУП|РУП|КУП|ОДО|ИП|ПК|СПК)\b", line, re.I)
                    and not CERT_RE.search(line)
                ),
                None,
            )
        if not organization:
            continue

        unp_text = value_after(block, ("УНП", "Учетный номер плательщика")) or " ".join(block)
        unp_match = re.search(r"\b\d{9}\b", unp_text)
        address = value_after(block, ("Место нахождения", "Адрес", "Место нахождения юридического лица"))
        issue_date = parse_date(value_after(block, ("Дата регистрации свидетельства", "Дата выдачи")))
        expiry_date = parse_date(value_after(block, ("Дата окончания действия свидетельства", "Действителен до")))
        status = value_after(block, ("Статус действия свидетельства", "Статус"))
        evaluator = value_after(block, ("Организация по оценке", "Орган по оценке"))

        records.append(
            {
                "cert_number": cert_number,
                "organization": organization,
                "unp": unp_match.group(0) if unp_match else None,
                "address": address,
                "evaluator": evaluator,
                "issue_date": issue_date,
                "expiry_date": expiry_date,
                "status": status,
            }
        )

    return records


def main() -> None:
    all_records: list[dict] = []
    seen: set[str] = set()

    for page_num in range(1, MAX_PAGES + 1):
        try:
            html = fetch_page(page_num)
        except Exception as exc:
            print(f"[SPK2] Ошибка страницы {page_num}: {exc}", file=sys.stderr)
            if page_num == 1:
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
        print(f"[SPK2] page={page_num}: parsed={len(page_records)}, new={added}, total={len(all_records)}")

        if not page_records or added == 0:
            break
        time.sleep(PAUSE_BETWEEN_PAGES)

    if not all_records:
        raise RuntimeError("Не найдено ни одной записи нового СПК; рабочий файл не перезаписан")

    output = {
        "source": "spk2",
        "source_name": "СПК новый",
        "url": BASE_URL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(all_records),
        "records": all_records,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SPK2] Saved {len(all_records)} records to {OUT_FILE}")


if __name__ == "__main__":
    main()

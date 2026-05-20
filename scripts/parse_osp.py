"""
Парсер ОСП (Орган сварочного производства) со stn.by

Сайт: https://stn.by/services/welding/welding_list
Структура: одна страница со списком всех ОСП
Объём: ~740 записей

Выходной файл: data/osp.json
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://stn.by/services/welding/welding_list"
OUT_FILE = Path("data/osp.json")
TIMEOUT = 60

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}


def parse_date(s):
    if not s:
        return None
    m = re.search(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", s)
    if not m:
        return None
    d, mo, y = m.groups()
    return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"


def fetch_html(url):
    print(f"[OSP] Запрос: {url}")
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    print(f"[OSP] Статус: {resp.status_code}, размер: {len(resp.text)} байт")
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
    return resp.text


def parse_osp_table(html):
    soup = BeautifulSoup(html, "html.parser")
    records = []

    rows = soup.find_all("tr")
    print(f"[OSP] Найдено tr: {len(rows)}")

    for row in rows:
        tds = row.find_all("td")
        if len(tds) < 2:
            continue

        cells = [td.get_text(" ", strip=True) for td in tds]
        # Пропустим заголовки
        if all(len(c) < 3 for c in cells):
            continue
        if any(c.lower() in ("№", "номер", "название", "название организации") for c in cells[:2]):
            continue

        # Структура из предыдущего теста: cells[0]=Название, cells[1]=Номер | дата
        # На самом деле там в одну строку: "Филиал \"Завод ЖБК\" 12-08-05/001 от 10.09.2015 заводские условия 2015-09-10 2018-09-10"
        organization = cells[0] if cells else None

        # Номер свидетельства
        cert_number = None
        for c in cells:
            m = re.search(r"\d{2}-\d{2}-\d{2}/\d+", c)
            if m:
                cert_number = m.group(0)
                break

        # Даты
        dates = []
        for c in cells:
            for m in re.finditer(r"\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4}", c):
                d = parse_date(m.group(0))
                if d:
                    dates.append(d)
        issue_date = dates[0] if dates else None
        expiry_date = dates[-1] if len(dates) > 1 else None

        # Вид (заводские условия / стройплощадка)
        activity = None
        for c in cells:
            if "заводск" in c.lower() or "стройплощадк" in c.lower():
                activity = c[:200]
                break

        # Скип пустых
        if not organization and not cert_number:
            continue

        records.append({
            "cert_number": cert_number,
            "organization": organization,
            "issue_date": issue_date,
            "expiry_date": expiry_date,
            "activity": activity,
            "raw": " | ".join(cells)[:500],
        })

    return records


def main():
    try:
        html = fetch_html(URL)
    except Exception as e:
        print(f"[OSP] ОШИБКА: {e}", file=sys.stderr)
        sys.exit(1)

    records = parse_osp_table(html)
    print(f"[OSP] Распарсено: {len(records)}")

    if len(records) == 0:
        debug_path = Path("data/osp_debug.html")
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(html[:50000], encoding="utf-8")
        print(f"[OSP] ВНИМАНИЕ: 0 записей. HTML сохранён в {debug_path}")

    out = {
        "source": "osp",
        "source_name": "ОСП (Орган сварочного производства)",
        "url": URL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(records),
        "records": records,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OSP] ✓ Сохранено в {OUT_FILE} ({OUT_FILE.stat().st_size // 1024} КБ)")


if __name__ == "__main__":
    main()

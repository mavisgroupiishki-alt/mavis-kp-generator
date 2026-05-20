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
    debug_samples = []

    # === Шаг 1: Найти ОСНОВНУЮ таблицу с данными ===
    # На странице может быть несколько table — выбираем самую большую (с >50 строками)
    all_tables = soup.find_all("table")
    print(f"[OSP] Всего таблиц на странице: {len(all_tables)}")
    for i, t in enumerate(all_tables):
        trs_in_table = t.find_all("tr")
        print(f"[OSP]   Таблица {i}: {len(trs_in_table)} строк")

    # Выбираем самую большую таблицу (с максимальным количеством строк)
    main_table = None
    if all_tables:
        main_table = max(all_tables, key=lambda t: len(t.find_all("tr")))
        rows = main_table.find_all("tr")
        print(f"[OSP] Выбрана таблица с {len(rows)} строками")
    else:
        # Если table нет — берём все tr на странице
        rows = soup.find_all("tr")
        print(f"[OSP] Таблиц <table> нет. Найдено tr на странице: {len(rows)}")

    if len(rows) < 5:
        print(f"[OSP] Слишком мало строк ({len(rows)}). Возможно нужная таблица не загрузилась.")
        return records, debug_samples

    # === Шаг 2: Определить структуру колонок по заголовку ===
    column_map = {}
    header_row_idx = None
    for i, row in enumerate(rows[:3]):  # заголовок обычно в первых 3 строках
        ths = row.find_all("th")
        if ths and len(ths) >= 2:
            headers = [th.get_text(" ", strip=True).lower() for th in ths]
            print(f"[OSP] Заголовки в строке {i}: {headers}")
            for idx, h in enumerate(headers):
                if "название" in h or "организац" in h or "наименование" in h:
                    column_map["organization"] = idx
                elif ("номер" in h and ("свид" in h or "регистрац" in h)) or h.strip() == "№":
                    column_map["cert_number"] = idx
                elif "выдач" in h or "начала" in h:
                    column_map["issue_date"] = idx
                elif "действ" in h or "окончан" in h or "срок" in h or h.startswith("по"):
                    column_map["expiry_date"] = idx
                elif "вид" in h or "услов" in h or "процесс" in h or "способ" in h:
                    column_map["activity"] = idx
            header_row_idx = i
            break

    print(f"[OSP] Карта колонок: {column_map}")

    # === Шаг 3: Парсим строки данных ===
    for ri, row in enumerate(rows):
        if header_row_idx is not None and ri <= header_row_idx:
            continue

        tds = row.find_all("td")
        if len(tds) < 2:
            continue

        cells = [td.get_text(" ", strip=True) for td in tds]

        if all(len(c) < 3 for c in cells):
            continue
        # Пропускаем явно служебные строки (если "название" внутри строки данных — это всё ещё заголовок)
        if any(c.lower() in ("№", "номер", "название", "название организации") for c in cells[:2]):
            continue

        # === Извлекаем поля ===
        organization = None
        cert_number = None
        issue_date = None
        expiry_date = None
        activity = None

        if column_map:
            # По карте колонок
            if "organization" in column_map and column_map["organization"] < len(cells):
                organization = cells[column_map["organization"]]
            if "cert_number" in column_map and column_map["cert_number"] < len(cells):
                cert_number_raw = cells[column_map["cert_number"]]
                m = re.search(r"\d{2}-\d{2}-\d{2}/\d+", cert_number_raw)
                cert_number = m.group(0) if m else cert_number_raw
            if "issue_date" in column_map and column_map["issue_date"] < len(cells):
                issue_date = parse_date(cells[column_map["issue_date"]])
            if "expiry_date" in column_map and column_map["expiry_date"] < len(cells):
                expiry_date = parse_date(cells[column_map["expiry_date"]])
            if "activity" in column_map and column_map["activity"] < len(cells):
                activity = cells[column_map["activity"]]

        # Если карта колонок не дала результата — эвристика
        if not organization:
            organization = cells[0] if cells else None
        if not cert_number:
            for c in cells:
                m = re.search(r"\d{2}-\d{2}-\d{2}/\d+", c)
                if m:
                    cert_number = m.group(0)
                    break
        if not expiry_date or not issue_date:
            all_text = " ".join(cells)
            # Дата выдачи: "от ДД.ММ.ГГГГ"
            if not issue_date:
                m_issue = re.search(r"от\s+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4})", all_text)
                if m_issue:
                    issue_date = parse_date(m_issue.group(1))
            # Дата окончания: ищем последнюю ISO-дату или последнюю ДД.ММ.ГГГГ
            if not expiry_date:
                iso_dates = re.findall(r"(\d{4})-(\d{2})-(\d{2})", all_text)
                valid_iso = [d for d in iso_dates if d[0] not in ("0000",)]
                if valid_iso:
                    y, mo, d = valid_iso[-1]
                    expiry_date = f"{y}-{mo}-{d}"
                else:
                    ddmm = re.findall(r"\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4}", all_text)
                    if len(ddmm) > 1:
                        expiry_date = parse_date(ddmm[-1])
        if not activity:
            for c in cells:
                if "заводск" in c.lower() or "стройплощадк" in c.lower():
                    activity = c[:200]
                    break

        if not organization and not cert_number:
            continue

        # Чистка
        if organization:
            organization = re.sub(r"\s+", " ", organization).strip()
        if activity:
            activity = re.sub(r"\s+", " ", activity).strip()[:300]

        # Сохраняем первые 5 записей с сырыми ячейками для диагностики
        if len(debug_samples) < 5:
            debug_samples.append({
                "row_index": ri,
                "cells_count": len(cells),
                "cells": cells,
                "parsed": {
                    "cert_number": cert_number,
                    "organization": organization,
                    "issue_date": issue_date,
                    "expiry_date": expiry_date,
                    "activity": activity,
                },
            })

        records.append({
            "cert_number": cert_number,
            "organization": organization,
            "issue_date": issue_date,
            "expiry_date": expiry_date,
            "activity": activity,
        })

    print(f"[OSP] === ДИАГНОСТИКА: первые {len(debug_samples)} записей ===")
    for s in debug_samples:
        print(f"[OSP] Строка {s['row_index']}: {len(s['cells'])} ячеек")
        for i, c in enumerate(s['cells']):
            print(f"  [{i}] {repr(c)[:120]}")
        print(f"  → cert={s['parsed']['cert_number']!r}, issue={s['parsed']['issue_date']!r}, expiry={s['parsed']['expiry_date']!r}")

    return records, debug_samples


def main():
    try:
        html = fetch_html(URL)
    except Exception as e:
        print(f"[OSP] ОШИБКА: {e}", file=sys.stderr)
        sys.exit(1)

    records, debug_samples = parse_osp_table(html)
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
        "_debug_samples": debug_samples,  # для отладки — первые 5 записей с сырыми ячейками
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OSP] ✓ Сохранено в {OUT_FILE} ({OUT_FILE.stat().st_size // 1024} КБ)")


if __name__ == "__main__":
    main()

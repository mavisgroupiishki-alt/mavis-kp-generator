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
    if m:
        d, mo, y = m.groups()
        return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
    # Также формат ГГГГ-ММ-ДД (на stn.by даты последней оценки в ISO-формате)
    m_iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m_iso:
        y, mo, d = m_iso.groups()
        return f"{y}-{mo}-{d}"
    return None


def add_months_to_date(iso_date: str, months: int):
    """Прибавить N месяцев к дате в формате ГГГГ-ММ-ДД. Возвращает новую дату или None."""
    if not iso_date:
        return None
    try:
        y, mo, d = iso_date.split("-")
        y, mo, d = int(y), int(mo), int(d)
        new_mo = mo + months
        new_y = y + (new_mo - 1) // 12
        new_mo = ((new_mo - 1) % 12) + 1
        # Учёт того, что в новом месяце может быть меньше дней (29 февраля → 28 февраля и т.п.)
        from calendar import monthrange
        max_day = monthrange(new_y, new_mo)[1]
        new_d = min(d, max_day)
        return f"{new_y:04d}-{new_mo:02d}-{new_d:02d}"
    except Exception:
        return None


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
                # Организация: "название", "наименование", "организация", "предприятие", "заявитель"
                if ("название" in h or "организац" in h or "наименование" in h
                    or "предприят" in h or "заявител" in h):
                    column_map["organization"] = idx
                # Номер: "номер свид", "номер регистрац", "№ свид", "рег.№", "регистрационный номер"
                elif (("номер" in h and ("свид" in h or "регистрац" in h))
                      or "рег.№" in h or "рег. №" in h
                      or ("№" in h and "свид" in h)
                      or h.strip() == "№"):
                    column_map["cert_number"] = idx
                # Дата выдачи
                elif "выдач" in h or "начала" in h:
                    column_map["issue_date"] = idx
                # Дата окончания
                elif "действ" in h or "окончан" in h or "срок" in h or h.startswith("по"):
                    column_map["expiry_date"] = idx
                # Вид деятельности / область
                elif ("вид" in h or "услов" in h or "процесс" in h
                      or "способ" in h or "область" in h or "распростран" in h):
                    column_map["activity"] = idx
            header_row_idx = i
            break

    print(f"[OSP] Карта колонок: {column_map}")

    # === Определяем количество колонок в записи ===
    # На сайте stn.by ВСЕ записи могут лежать в ОДНОЙ <tr> подряд — много групп ячеек.
    # 743 строк × 5 ячеек = 3715 ячеек в одной строке.
    # Поэтому если в строке очень много td — разбиваем её на группы.
    cols_per_record = max(column_map.values()) + 1 if column_map else 5
    print(f"[OSP] Колонок на одну запись: {cols_per_record}")

    # === Шаг 3: Парсим строки данных ===
    def process_row_cells(all_cells, row_idx):
        """Обработать одну группу ячеек как запись (внутри функции, чтобы видеть column_map и debug_samples)"""
        if len(all_cells) < cols_per_record:
            return None

        # Берём ровно cols_per_record ячеек
        cells = all_cells[:cols_per_record]

        if all(len(c) < 3 for c in cells):
            return None
        if any(c.lower() in ("№", "номер", "название", "название организации", "предприятие") for c in cells[:2]):
            return None

        # === Извлекаем поля ===
        organization = None
        cert_number = None
        issue_date = None
        last_check_date = None
        expiry_date = None
        activity = None

        if column_map:
            if "organization" in column_map and column_map["organization"] < len(cells):
                organization = cells[column_map["organization"]]
            if "cert_number" in column_map and column_map["cert_number"] < len(cells):
                cert_number_raw = cells[column_map["cert_number"]]
                m = re.search(r"\d{2}-\d{2}-\d{2}/\d+", cert_number_raw)
                cert_number = m.group(0) if m else cert_number_raw
            if "issue_date" in column_map and column_map["issue_date"] < len(cells):
                issue_date = parse_date(cells[column_map["issue_date"]])
            if "expiry_date" in column_map and column_map["expiry_date"] < len(cells):
                last_check_date = parse_date(cells[column_map["expiry_date"]])
            if "activity" in column_map and column_map["activity"] < len(cells):
                activity = cells[column_map["activity"]]

        # Эвристика для пропущенных полей
        if not organization:
            organization = cells[0] if cells else None
        if not cert_number:
            for c in cells:
                m = re.search(r"\d{2}-\d{2}-\d{2}/\d+", c)
                if m:
                    cert_number = m.group(0)
                    break
        if not last_check_date or not issue_date:
            all_text = " ".join(cells)
            if not issue_date:
                m_issue = re.search(r"от\s+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4})", all_text)
                if m_issue:
                    issue_date = parse_date(m_issue.group(1))
            if not last_check_date:
                iso_dates = re.findall(r"(\d{4})-(\d{2})-(\d{2})", all_text)
                valid_iso = [d for d in iso_dates if d[0] not in ("0000",)]
                if valid_iso:
                    y, mo, d = valid_iso[-1]
                    last_check_date = f"{y}-{mo}-{d}"

        # Рассчитываем expiry_date = max(last_check_date, issue_date) + 18 месяцев
        base_date = last_check_date or issue_date
        if base_date:
            expiry_date = add_months_to_date(base_date, 18)

        if not activity:
            for c in cells:
                if "заводск" in c.lower() or "стройплощадк" in c.lower():
                    activity = c[:200]
                    break

        # Пропускаем пустые служебные строки (даты "0000-00-00" — это пустышки в первой строке)
        if not organization and not cert_number:
            return None
        # Если организация и cert_number пустые/служебные — тоже скип
        if organization and len(organization) < 3 and not cert_number:
            return None

        if organization:
            organization = re.sub(r"\s+", " ", organization).strip()
        if activity:
            activity = re.sub(r"\s+", " ", activity).strip()[:300]

        record = {
            "cert_number": cert_number,
            "organization": organization,
            "issue_date": issue_date,
            "last_check_date": last_check_date,
            "expiry_date": expiry_date,
            "activity": activity,
        }

        if len(debug_samples) < 5:
            debug_samples.append({
                "row_index": row_idx,
                "cells_count": len(cells),
                "cells": cells,
                "parsed": record,
            })

        return record

    for ri, row in enumerate(rows):
        if header_row_idx is not None and ri <= header_row_idx:
            continue

        tds = row.find_all("td")
        if len(tds) < 2:
            continue

        all_cells = [td.get_text(" ", strip=True) for td in tds]

        # Если в строке количество ячеек кратно cols_per_record и существенно больше — это сборная строка
        if len(all_cells) >= cols_per_record * 2:
            print(f"[OSP] Строка {ri}: {len(all_cells)} ячеек, разбиваю на группы по {cols_per_record}")
            for offset in range(0, len(all_cells), cols_per_record):
                group = all_cells[offset:offset + cols_per_record]
                rec = process_row_cells(group, ri)
                if rec:
                    records.append(rec)
        else:
            # Обычная строка — одна запись
            rec = process_row_cells(all_cells, ri)
            if rec:
                records.append(rec)

    print(f"[OSP] === ДИАГНОСТИКА: первые {len(debug_samples)} записей ===")
    for s in debug_samples:
        print(f"[OSP] Строка {s['row_index']}: {len(s['cells'])} ячеек")
        for i, c in enumerate(s['cells']):
            print(f"  [{i}] {repr(c)[:120]}")
        print(f"  → cert={s['parsed']['cert_number']!r}, issue={s['parsed']['issue_date']!r}, last_check={s['parsed']['last_check_date']!r}, expiry(+18мес)={s['parsed']['expiry_date']!r}")

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

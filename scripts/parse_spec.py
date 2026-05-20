"""
Парсер Квалификационных аттестатов специалистов с rcuk.bsc.by

Сайт: https://rcuk.bsc.by/att_search
Структура: таблица с пагинацией (по 50 записей)
Объём: ~10,000-15,000 записей

Выходной файл: data/spec.json
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://rcuk.bsc.by/att_search"
OUT_FILE = Path("data/spec.json")
TIMEOUT = 60
PER_PAGE = 50
MAX_PAGES = 400
PAUSE_BETWEEN_PAGES = 1.5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
}


def parse_date(s):
    if not s:
        return None
    m = re.search(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", s)
    if not m:
        return None
    d, mo, y = m.groups()
    return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"


def fetch_page(page_num):
    params = {"items_per_page": PER_PAGE}
    if page_num > 0:
        params["page"] = page_num
    print(f"[SPEC] Страница {page_num + 1}")
    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    return resp.text


def parse_page(html):
    soup = BeautifulSoup(html, "html.parser")
    records = []

    rows = soup.find_all("tr")
    for row in rows:
        tds = row.find_all("td")
        if len(tds) < 3:
            continue

        cells = [td.get_text(" ", strip=True) for td in tds]
        if any(c.lower() in ("№", "ф.и.о.", "фио", "специализация", "квалификация") for c in cells[:3]):
            continue

        # Структура: № аттестата | ФИО | Специализация | Срок действия
        cert_number = None
        for c in cells:
            # Формат вроде BY-112-... или 00-04-... 
            if re.match(r"^[A-Z\d][\d\-/\.A-Z\s]{5,}$", c):
                cert_number = c.strip()
                break

        # ФИО — ячейка содержащая 2-3 слова с заглавных букв на кириллице
        person = None
        for c in cells:
            if re.match(r"^[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(\s+[А-ЯЁ][а-яё]+)?$", c.strip()):
                person = c.strip()
                break
        # Альтернатива — самая короткая текстовая ячейка с фамилией
        if not person:
            text_cells = [c for c in cells if re.search(r"[А-Яа-яЁё]{3,}", c) and len(c) < 80]
            if text_cells:
                person = text_cells[0]

        # Специализация — длинная текстовая ячейка
        specialization = None
        text_cells_long = [c for c in cells if re.search(r"[А-Яа-яЁё]{3,}", c) and len(c) > 30]
        if text_cells_long:
            specialization = text_cells_long[0][:300]

        # Дата окончания
        expiry_date = None
        for c in cells:
            d = parse_date(c)
            if d:
                expiry_date = d

        if not cert_number and not person:
            continue

        records.append({
            "cert_number": cert_number,
            "person": person,
            "specialization": specialization,
            "expiry_date": expiry_date,
        })

    return records


def has_next_page(html, current_page):
    soup = BeautifulSoup(html, "html.parser")
    pagination = soup.find_all("a", href=re.compile(r"page=\d+"))
    next_page_num = current_page + 1
    for a in pagination:
        if f"page={next_page_num}" in (a.get("href") or ""):
            return True
    return False


def main():
    all_records = []
    page = 0

    while page < MAX_PAGES:
        try:
            html = fetch_page(page)
        except Exception as e:
            print(f"[SPEC] ОШИБКА на странице {page + 1}: {e}", file=sys.stderr)
            if page == 0:
                sys.exit(1)
            break

        page_records = parse_page(html)
        print(f"[SPEC] Страница {page + 1}: {len(page_records)}")

        if not page_records:
            break

        all_records.extend(page_records)

        if not has_next_page(html, page):
            break

        page += 1
        time.sleep(PAUSE_BETWEEN_PAGES)

    print(f"[SPEC] Всего: {len(all_records)}")

    # Дедупликация
    seen = set()
    uniq = []
    for r in all_records:
        key = (r.get("cert_number") or "", r.get("person") or "")
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    print(f"[SPEC] Уникальных: {len(uniq)}")

    out = {
        "source": "spec",
        "source_name": "Квалификационные аттестаты специалистов",
        "url": BASE_URL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(uniq),
        "records": uniq,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SPEC] ✓ Сохранено: {OUT_FILE.stat().st_size // 1024} КБ")


if __name__ == "__main__":
    main()

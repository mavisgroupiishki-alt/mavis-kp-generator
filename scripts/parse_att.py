"""
Парсер Аттестатов соответствия юр.лиц с att.bsc.by

Сайт: https://att.bsc.by/reestr
Структура: таблица с пагинацией (по 50 записей на странице)
Объём: ~3000-5000 записей (~60-100 страниц)

Выходной файл: data/att.json
"""

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
MAX_PAGES = 150        # защита от бесконечного цикла
PAUSE_BETWEEN_PAGES = 1.5  # секунд между страницами (чтобы не блокнуть)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24", "Google Chrome";v="131"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
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
    """Скачать одну страницу пагинации"""
    params = {"items_per_page": PER_PAGE}
    if page_num > 0:
        params["page"] = page_num
    print(f"[ATT] Запрос страницы {page_num + 1}: {BASE_URL}")
    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    return resp.text


def parse_page(html):
    """Распарсить таблицу с одной страницы"""
    soup = BeautifulSoup(html, "html.parser")
    records = []

    rows = soup.find_all("tr")
    for row in rows:
        tds = row.find_all("td")
        if len(tds) < 3:
            continue

        cells = [td.get_text(" ", strip=True) for td in tds]
        # Пропускаем заголовочные
        if any(c.lower() in ("№", "номер аттестата", "наименование", "наименование организации", "виды работ") for c in cells):
            continue

        # Структура att.bsc.by обычно: № аттестата | Организация (ОПФ) | Виды работ | Срок действия
        cert_number = None
        for c in cells:
            # Формат BY/112 06.01 01.7.6 0143 или похожие
            m = re.search(r"BY[\/\s][\d\s\.\/-]+", c)
            if m:
                cert_number = m.group(0).strip()
                break
            # Или просто номер с дефисами
            m2 = re.search(r"^\d{2,}[\d\-/]+$", c)
            if m2 and len(c) > 5:
                cert_number = c
                break

        # Организация — самая длинная текстовая ячейка с буквами
        text_cells = [(i, c) for i, c in enumerate(cells) if re.search(r"[А-Яа-яA-Za-z]{5,}", c)]
        organization = None
        activity = None
        if text_cells:
            sorted_text = sorted(text_cells, key=lambda x: len(x[1]), reverse=True)
            organization = sorted_text[0][1]
            if len(sorted_text) > 1:
                activity = sorted_text[1][1][:300]

        # Дата окончания (срок действия)
        expiry_date = None
        for c in cells:
            d = parse_date(c)
            if d:
                expiry_date = d  # берём последнюю найденную
        
        if not cert_number and not organization:
            continue

        records.append({
            "cert_number": cert_number,
            "organization": organization,
            "activity": activity,
            "expiry_date": expiry_date,
        })

    return records


def has_next_page(html, current_page):
    """Проверить, есть ли следующая страница"""
    soup = BeautifulSoup(html, "html.parser")
    # На bsc.by пагинация обычно через ?page=N
    # Признак следующей: есть ссылка с page=current+1
    pagination = soup.find_all("a", href=re.compile(r"page=\d+"))
    next_page_num = current_page + 1
    for a in pagination:
        if f"page={next_page_num}" in (a.get("href") or ""):
            return True
    # Альтернатива — кнопка "next"/"следующая"
    for a in pagination:
        text = a.get_text(" ", strip=True).lower()
        if "след" in text or "next" in text or "»" in text:
            return True
    return False


def main():
    all_records = []
    page = 0

    while page < MAX_PAGES:
        try:
            html = fetch_page(page)
        except Exception as e:
            print(f"[ATT] ОШИБКА на странице {page + 1}: {e}", file=sys.stderr)
            if page == 0:
                # Если упало на первой странице — выходим с ошибкой
                sys.exit(1)
            # Иначе — продолжаем с тем что есть
            break

        page_records = parse_page(html)
        print(f"[ATT] Страница {page + 1}: распарсено {len(page_records)}")

        if not page_records:
            print("[ATT] Записей на странице нет, завершаем")
            break

        all_records.extend(page_records)

        if not has_next_page(html, page):
            print(f"[ATT] Страница {page + 1} — последняя")
            break

        page += 1
        time.sleep(PAUSE_BETWEEN_PAGES)

    print(f"[ATT] Всего распарсено: {len(all_records)}")

    # Удаляем дубликаты по номеру
    seen = set()
    uniq = []
    for r in all_records:
        key = (r.get("cert_number") or "", r.get("organization") or "")
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    print(f"[ATT] Уникальных: {len(uniq)}")

    out = {
        "source": "att",
        "source_name": "Аттестаты соответствия юр.лиц (Белстройцентр)",
        "url": BASE_URL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(uniq),
        "records": uniq,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ATT] ✓ Сохранено в {OUT_FILE} ({OUT_FILE.stat().st_size // 1024} КБ)")


if __name__ == "__main__":
    main()

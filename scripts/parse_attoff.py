"""
Парсер ОТМЕНЁННЫХ Аттестатов соответствия юр.лиц с att.bsc.by/reestrnone

Сайт: https://att.bsc.by/reestrnone
Структура: таблица с пагинацией (по 50 записей на странице).
Колонки: Организация | УНП | (доп.инфо) | № аттестата | Виды работ | Дата выдачи | Срок | Статус | Основание

Выходной файл: data/attoff.json
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://att.bsc.by/reestrnone"
OUT_FILE = Path("data/attoff.json")
TIMEOUT = 60
PER_PAGE = 50
MAX_PAGES = 100
PAUSE_BETWEEN_PAGES = 1.5

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
    if y == "0000" or mo == "00" or d == "00":
        return None
    return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"


def fetch_page(page_num):
    params = {"items_per_page": PER_PAGE}
    if page_num > 0:
        params["page"] = page_num
    print(f"[ATTOFF] Запрос страницы {page_num + 1}: {BASE_URL}")
    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    return resp.text


def parse_page(html):
    """Распарсить таблицу отменённых аттестатов с одной страницы"""
    soup = BeautifulSoup(html, "html.parser")
    records = []

    rows = soup.find_all("tr")
    for row in rows:
        tds = row.find_all("td")
        if len(tds) < 6:
            continue

        cells = [td.get_text(" ", strip=True) for td in tds]
        # Пропускаем заголовочные строки
        if any(c.lower() in ("№", "наименование", "унп", "виды работ", "основание") for c in cells):
            continue

        # Структура (по наблюдениям на att.bsc.by/reestrnone):
        #   [0] Организация | [1] УНП | [3] № аттестата | [4] Виды работ | [5] Дата выдачи | [6] Срок/Дата прекращения | [7] Статус | [8] Основание

        organization = cells[0] if len(cells) > 0 else ""
        unp_raw = cells[1] if len(cells) > 1 else ""
        unp = re.search(r"\d{9}", unp_raw)
        unp = unp.group(0) if unp else None

        # Номер аттестата — ищем по формату
        cert_number = None
        for c in cells:
            m = re.search(r"BY[\/\s][\d\s\.\/-]{5,}", c)
            if m:
                cert_number = m.group(0).strip()
                break
            m2 = re.match(r"^\d{4,}[\d\-/]+$", c.strip())
            if m2 and len(c.strip()) >= 8:
                cert_number = c.strip()
                break

        # Виды работ — обычно длинная строка с описанием
        activity = None
        for c in cells:
            if c == organization or c == unp_raw or c == cert_number:
                continue
            if re.search(r"[А-Яа-я]{8,}", c) and len(c) > 20:
                activity = c[:500]
                break

        # Даты: ищем все даты, первая = выдача, последняя = прекращение
        dates = []
        for c in cells:
            d = parse_date(c)
            if d:
                dates.append(d)
        issue_date = dates[0] if dates else None
        expiry_date = dates[-1] if len(dates) > 1 else None

        # Статус (Прекращён / Истёк / Аннулирован)
        status = None
        for c in cells:
            if re.search(r"прекращ|истёк|истек|аннулирован", c, re.IGNORECASE):
                status = c
                break

        # Основание прекращения — обычно последняя ячейка с текстом про "абз." или "п."
        cancellation_reason = None
        cancellation_url = None
        for i, c in enumerate(cells):
            if re.search(r"абз\.?\s*\d+\s*п\.?\s*\d+|п\.?\s*\d+\.\d+|подпункт|постановл|Кодекс", c, re.IGNORECASE):
                cancellation_reason = c
                # Ищем ссылку на постановление в этой ячейке
                if i < len(tds):
                    a = tds[i].find("a")
                    if a and a.get("href"):
                        cancellation_url = urljoin(BASE_URL, a["href"])
                break

        if not cert_number and not organization:
            continue

        records.append({
            "cert_number": cert_number,
            "organization": organization,
            "unp": unp,
            "activity": activity,
            "issue_date": issue_date,
            "expiry_date": expiry_date,
            "status": status,
            "cancellation_reason": cancellation_reason,
            "cancellation_url": cancellation_url,
        })

    return records


def has_next_page(html, current_page):
    soup = BeautifulSoup(html, "html.parser")
    next_link = soup.find("a", href=re.compile(rf"[?&]page={current_page + 1}\b"))
    if next_link:
        return True
    # Альтернатива — посмотреть текст пагинатора
    pager = soup.find("ul", class_=re.compile(r"pager|pagination"))
    if pager:
        return bool(pager.find("a", class_=re.compile(r"next|»")))
    return False


def main():
    all_records = []
    seen_keys = set()
    
    for page_num in range(MAX_PAGES):
        try:
            html = fetch_page(page_num)
        except Exception as e:
            print(f"[ATTOFF] ОШИБКА на странице {page_num + 1}: {e}", file=sys.stderr)
            break

        page_records = parse_page(html)
        new_count = 0
        for r in page_records:
            key = (r.get("cert_number") or "") + "|" + (r.get("organization") or "")[:60]
            if key in seen_keys:
                continue
            seen_keys.add(key)
            all_records.append(r)
            new_count += 1

        print(f"[ATTOFF] Страница {page_num + 1}: {len(page_records)} записей (новых {new_count}), всего: {len(all_records)}")

        if new_count == 0 and page_num > 0:
            print("[ATTOFF] На странице нет новых записей — достигнут конец")
            break

        if not has_next_page(html, page_num):
            print("[ATTOFF] Нет ссылки на следующую страницу")
            break

        time.sleep(PAUSE_BETWEEN_PAGES)

    print(f"[ATTOFF] Распарсено записей: {len(all_records)}")

    out = {
        "source": "attoff",
        "source_name": "Аттестаты отменённые/прекращённые",
        "url": BASE_URL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(all_records),
        "records": all_records,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ATTOFF] ✓ Сохранено в {OUT_FILE} ({OUT_FILE.stat().st_size // 1024} КБ)")


if __name__ == "__main__":
    main()

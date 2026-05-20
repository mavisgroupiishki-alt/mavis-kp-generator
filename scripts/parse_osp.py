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

        organization = cells[0] if cells else None

        # Номер свидетельства — формат NN-NN-NN/NNN
        cert_number = None
        for c in cells:
            m = re.search(r"\d{2}-\d{2}-\d{2}/\d+", c)
            if m:
                cert_number = m.group(0)
                break

        # Даты:
        # На странице stn.by обычно есть формат "от ДД.ММ.ГГГГ" — дата выдачи,
        # и где-то справа дата окончания в виде ГГГГ-ММ-ДД.
        # Соберём все даты по типам отдельно
        all_text = " ".join(cells)
        issue_date = None
        expiry_date = None

        # Дата выдачи: "от ДД.ММ.ГГГГ"
        m_issue = re.search(r"от\s+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4})", all_text)
        if m_issue:
            issue_date = parse_date(m_issue.group(1))

        # Дата окончания: ищем все даты в формате ГГГГ-MM-DD (это формат который сайт выводит для срока действия)
        iso_dates = re.findall(r"(\d{4})-(\d{2})-(\d{2})", all_text)
        if iso_dates:
            # Если несколько ISO-дат — берём последнюю (она обычно дата окончания)
            # Игнорируем явно пустые 0000-00-00
            valid = [d for d in iso_dates if d[0] != "0000"]
            if valid:
                y, mo, d = valid[-1]
                expiry_date = f"{y}-{mo}-{d}"

        # Если ISO-формата не нашли — берём последнюю ДД.ММ.ГГГГ как дату окончания (не первую, которая "от")
        if not expiry_date:
            ddmm_dates = re.findall(r"\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4}", all_text)
            # Первая идёт после "от", вторая+ может быть окончанием
            if len(ddmm_dates) > 1:
                expiry_date = parse_date(ddmm_dates[-1])

        # Вид (заводские условия / стройплощадка)
        activity = None
        for c in cells:
            if "заводск" in c.lower() or "стройплощадк" in c.lower():
                activity = c[:200]
                break

        if not organization and not cert_number:
            continue

        records.append({
            "cert_number": cert_number,
            "organization": organization,
            "issue_date": issue_date,
            "expiry_date": expiry_date,
            "activity": activity,
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

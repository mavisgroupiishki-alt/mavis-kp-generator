"""
Парсер СПК (Свидетельства о технической компетентности) с bsc.by

Сайт: https://bsc.by/ru/building/ip
Структура: одна страница со списком всех СПК в виде HTML-таблицы
Объём: ~1500-2000 записей

Выходной файл: data/spk.json
{
  "source": "spk",
  "source_name": "СПК (Белстройцентр)",
  "url": "https://bsc.by/ru/building/ip",
  "updated_at": "2026-05-20T00:03:15Z",
  "count": 1843,
  "records": [
    {
      "cert_number": "12-08-05/001",
      "organization": "Филиал \"Завод ЖБК\" ...",
      "issue_date": "2015-09-10",
      "expiry_date": "2018-09-10",
      "activity": "..."
    },
    ...
  ]
}
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# === Конфигурация ===
URL = "https://bsc.by/ru/building/ip"
OUT_FILE = Path("data/spk.json")
TIMEOUT = 60

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24", "Google Chrome";v="131"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


def parse_date(s: str):
    """ДД.ММ.ГГГГ → ГГГГ-ММ-ДД, иначе None"""
    if not s:
        return None
    m = re.search(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", s)
    if not m:
        return None
    d, mo, y = m.groups()
    return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"


def fetch_html(url: str) -> str:
    print(f"[SPK] Запрос: {url}")
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    print(f"[SPK] Статус: {resp.status_code}, размер: {len(resp.text)} байт")
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
    return resp.text


def parse_spk_table(html: str):
    """Парсит HTML-таблицу со страницы СПК"""
    soup = BeautifulSoup(html, "html.parser")
    records = []

    # Структура bsc.by — все СПК в одной таблице.
    # Ищем все <tr>, у которых >=3 <td>
    rows = soup.find_all("tr")
    print(f"[SPK] Найдено tr на странице: {len(rows)}")

    for row in rows:
        tds = row.find_all("td")
        if len(tds) < 3:
            continue

        cells = [td.get_text(" ", strip=True) for td in tds]
        # Пропускаем заголовочные строки
        if all(len(c) < 3 for c in cells):
            continue
        if any("№" == c for c in cells[:2]):
            continue

        # Структура (по предыдущему опыту): № | Название | Дата выдачи | Дата окончания | ...
        # Или: Cert_number | Organization | ...
        # Будем гибкими: первая ячейка с буквами/цифрами и слэшами — это номер
        cert_number = None
        organization = None
        issue_date = None
        expiry_date = None

        # Ищем первую ячейку выглядящую как номер сертификата (12-08-05/001 или похожее)
        for i, c in enumerate(cells):
            if re.match(r"^[\d\-/.]+$", c) and "/" in c and i < 3:
                cert_number = c
                break

        # Название — самая длинная ячейка с буквами
        text_cells = [(i, c) for i, c in enumerate(cells) if re.search(r"[А-Яа-яA-Za-z]{3,}", c)]
        if text_cells:
            # Берём ту, что содержит максимум букв (название обычно самое длинное)
            organization = max(text_cells, key=lambda x: len(x[1]))[1]

        # Даты — ищем все даты в формате ДД.ММ.ГГГГ во всех ячейках
        dates = []
        for c in cells:
            d = parse_date(c)
            if d:
                dates.append(d)
        if dates:
            issue_date = dates[0]
            if len(dates) > 1:
                expiry_date = dates[-1]

        if not cert_number and not organization:
            continue

        records.append({
            "cert_number": cert_number,
            "organization": organization,
            "issue_date": issue_date,
            "expiry_date": expiry_date,
            "raw": " | ".join(cells)[:500],  # для отладки если что-то пошло не так
        })

    return records


def main():
    try:
        html = fetch_html(URL)
    except Exception as e:
        print(f"[SPK] ОШИБКА запроса: {e}", file=sys.stderr)
        sys.exit(1)

    records = parse_spk_table(html)
    print(f"[SPK] Распарсено записей: {len(records)}")

    if len(records) == 0:
        # Сохраним сырой HTML для диагностики
        debug_path = Path("data/spk_debug.html")
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(html[:50000], encoding="utf-8")
        print(f"[SPK] ВНИМАНИЕ: 0 записей. Сохранён первый кусок HTML в {debug_path} для отладки.")

    out = {
        "source": "spk",
        "source_name": "СПК (Свидетельства о технической компетентности)",
        "url": URL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(records),
        "records": records,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SPK] ✓ Сохранено в {OUT_FILE} ({OUT_FILE.stat().st_size // 1024} КБ)")


if __name__ == "__main__":
    main()

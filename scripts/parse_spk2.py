"""
Парсер СПК новый (Свидетельства о квалификации) — spk.bsc.by

Сайт: https://spk.bsc.by/cert_register
Структура: обычный HTML с пагинацией через GET-параметры (НЕ SPA).
Параметры: pageNumber=N&pageSize=K[&searchString=...]
Объём: ~1000-2000 записей

Выходной файл: data/spk2.json
"""

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
MAX_PAGES = 100
PAUSE_BETWEEN_PAGES = 1.0

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
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
    params = {"pageNumber": page_num, "pageSize": PAGE_SIZE}
    print(f"[SPK2] Запрос страницы {page_num}")
    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    return resp.text


def parse_page(html):
    """Парсим карточки СПК"""
    soup = BeautifulSoup(html, "html.parser")
    records = []

    # Структура карточки: ищем все блоки которые содержат "Регистрационный номер свидетельства"
    # Каждая карточка имеет это поле, и от неё легко взять остальные.
    # Берём текст всей страницы и режем на блоки по маркеру
    page_text = soup.get_text("\n", strip=True)
    
    # Находим все позиции "Регистрационный номер свидетельства"
    marker = "Регистрационный номер свидетельства"
    positions = []
    start = 0
    while True:
        idx = page_text.find(marker, start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + len(marker)

    if not positions:
        return records

    # Каждая карточка — это кусок текста от positions[i] до positions[i+1]
    for i, pos in enumerate(positions):
        next_pos = positions[i + 1] if i + 1 < len(positions) else len(page_text)
        block = page_text[pos:next_pos]
        
        # Извлекаем поля
        cert = re.search(r"Регистрационный номер свидетельства\s*\n?([^\n]+)", block)
        if not cert:
            continue
        cert_number = cert.group(1).strip()
        
        # Юридическое лицо — после маркера "Юридическое лицо" или просто текст "ОАО..." / "УП..." / "ЗАО..."
        org = re.search(r"Юридическое лицо\s*\n?(?:Унитарная организация\s*\n?|Полное\s+название\s*\n?)?([^\n]{5,300})", block)
        organization = None
        if org:
            organization = org.group(1).strip()
        else:
            # Альтернатива: ищем строку в кавычках или с ОПФ
            org_alt = re.search(r"([ЗОУЧАЕИКЛМНПРСТФХ][А-Я]{1,3}\s+[«\"][^«»\"]{3,200}[»\"])", block)
            if org_alt:
                organization = org_alt.group(1).strip()
        
        # Даты
        date_reg = re.search(r"Дата\s+регистрации\s+свидетельства\s*\n?(\d{2}\.\d{2}\.\d{4})", block)
        issue_date = parse_date(date_reg.group(1)) if date_reg else None
        
        date_exp = re.search(r"Дата\s+окончания\s+действия\s+свидетельства\s*\n?(\d{2}\.\d{2}\.\d{4})", block)
        expiry_date = parse_date(date_exp.group(1)) if date_exp else None
        
        # Статус
        status_m = re.search(r"Статус\s+действия\s+свидетельства\s*\n?([А-ЯЁа-яё]+)", block)
        status = status_m.group(1).strip() if status_m else None
        
        # Место нахождения (адрес)
        addr_m = re.search(r"Место\s+нахождения[^:\n]*:?\s*\n?([^\n]{10,300})", block)
        address = addr_m.group(1).strip() if addr_m else None
        
        # УНП
        unp_m = re.search(r"\b(\d{9})\b", block)
        unp = unp_m.group(1) if unp_m else None
        
        records.append({
            "cert_number": cert_number,
            "organization": organization,
            "unp": unp,
            "address": address,
            "issue_date": issue_date,
            "expiry_date": expiry_date,
            "status": status,
        })

    return records


def main():
    all_records = []
    seen_certs = set()
    
    for page_num in range(1, MAX_PAGES + 1):
        try:
            html = fetch_page(page_num)
        except Exception as e:
            print(f"[SPK2] ОШИБКА на странице {page_num}: {e}", file=sys.stderr)
            break

        page_records = parse_page(html)
        new_count = 0
        for r in page_records:
            cert = r.get("cert_number") or ""
            if cert in seen_certs:
                continue
            seen_certs.add(cert)
            all_records.append(r)
            new_count += 1

        print(f"[SPK2] Страница {page_num}: {len(page_records)} записей (новых {new_count}), всего: {len(all_records)}")

        if new_count == 0 and page_num > 1:
            print("[SPK2] Нет новых записей — конец")
            break
        if len(page_records) == 0:
            print("[SPK2] Страница пустая — конец")
            break

        time.sleep(PAUSE_BETWEEN_PAGES)

    print(f"[SPK2] Распарсено записей: {len(all_records)}")

    if len(all_records) == 0:
        # Отладка
        debug = Path("data/spk2_debug.html")
        debug.parent.mkdir(parents=True, exist_ok=True)
        try:
            html = fetch_page(1)
            debug.write_text(html[:80000], encoding="utf-8")
            print(f"[SPK2] Сохранён дамп в {debug}")
        except Exception:
            pass

    out = {
        "source": "spk2",
        "source_name": "СПК новый (Свидетельства о квалификации)",
        "url": BASE_URL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(all_records),
        "records": all_records,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SPK2] ✓ Сохранено в {OUT_FILE} ({OUT_FILE.stat().st_size // 1024} КБ)")


if __name__ == "__main__":
    main()

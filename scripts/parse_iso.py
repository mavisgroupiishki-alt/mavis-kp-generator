"""
Парсер сертификатов систем менеджмента (ISO 9001, СУОТ и т.д.) с tsouz.belgiss.by

Сайт: https://tsouz.belgiss.by/#!/certsm/certifs
Это Angular SPA, поэтому пробуем найти JSON API endpoint напрямую.

Известные API endpoints этого сайта (могут меняться):
- /api/public/certifs (списки сертификатов)
- /api/csm/list (системы менеджмента)
- /api/registry (универсальный)

Скрипт пробует несколько известных API endpoints и сохраняет данные.

Выходной файл: data/iso.json
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "https://tsouz.belgiss.by"
OUT_FILE = Path("data/iso.json")
TIMEOUT = 60

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Referer": BASE + "/",
    "Origin": BASE,
}

# Возможные API endpoints для системы менеджмента — пробуем по очереди
API_CANDIDATES = [
    # JSON API скорее всего такие:
    "/api/public/certifs/CSM",
    "/api/csm/list",
    "/api/csm/all",
    "/api/registry/csm",
    "/api/registry/list?type=CSM",
    "/api/v1/csm",
    "/api/v1/certs?type=csm",
    "/api/registries/csm/list",
    "/registries/csm.json",
    # Запасные варианты
    "/api/list?type=certsm",
    "/api/certs/list?type=sm",
]


def try_api():
    """Пытаемся найти рабочий JSON API"""
    print(f"[ISO] Сначала прогреваем сессию: GET {BASE}/")
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        r0 = s.get(BASE + "/", timeout=TIMEOUT)
        print(f"[ISO] Главная: HTTP {r0.status_code}, размер {len(r0.text)} байт")
    except Exception as e:
        print(f"[ISO] Не удалось загрузить главную: {e}")
        return None

    for path in API_CANDIDATES:
        url = BASE + path
        try:
            r = s.get(url, timeout=TIMEOUT)
            ct = (r.headers.get("Content-Type") or "").lower()
            print(f"[ISO] GET {path} → {r.status_code} ({ct.split(';')[0]})")
            if r.status_code == 200 and "json" in ct:
                try:
                    data = r.json()
                    # Проверяем что это похоже на список сертификатов
                    if isinstance(data, list) and len(data) > 0:
                        print(f"[ISO] ✓ Найден API: {path} (записей: {len(data)})")
                        return {"url": url, "data": data}
                    elif isinstance(data, dict):
                        # Ищем массив с записями в типичных полях
                        for key in ("data", "items", "results", "records", "list", "Items"):
                            if key in data and isinstance(data[key], list) and len(data[key]) > 0:
                                print(f"[ISO] ✓ Найден API: {path}, ключ '{key}' (записей: {len(data[key])})")
                                return {"url": url, "data": data[key]}
                        # Может быть пагинация — total > 0
                        if "total" in data or "count" in data:
                            print(f"[ISO] ? API ответил пагинацией: {data}")
                except Exception as e:
                    print(f"[ISO] Не JSON: {e}")
        except Exception as e:
            print(f"[ISO] {path}: ошибка {e}")
        time.sleep(0.3)

    return None


def normalize_records(raw_records):
    """Привести записи к нашему формату"""
    out = []
    for r in raw_records:
        if not isinstance(r, dict):
            continue
        # Универсальная попытка вытащить поля независимо от формата API
        item = {}
        # Номер сертификата
        for k in ("DocStartNumber", "RegNumber", "Number", "CertNumber", "number", "certNumber", "regNumber"):
            if k in r and r[k]:
                item["cert_number"] = str(r[k]).strip()
                break
        # Заявитель / организация
        for k in ("ApplicantName", "Applicant", "ProducerName", "Producer", "applicantName", "organization", "ManufacturerName"):
            if k in r and r[k]:
                item["organization"] = str(r[k]).strip()
                break
        # Дата выдачи
        for k in ("DocStartDate", "RegDate", "IssueDate", "issueDate"):
            if k in r and r[k]:
                d = str(r[k])[:10]
                item["issue_date"] = d
                break
        # Дата окончания
        for k in ("DocEndDate", "ExpiryDate", "EndDate", "expiryDate", "Suspended"):
            if k in r and r[k]:
                d = str(r[k])[:10]
                item["expiry_date"] = d
                break
        # Объект оценки
        for k in ("ObjectName", "Object", "Activity", "Scope", "object", "scope"):
            if k in r and r[k]:
                item["activity"] = str(r[k])[:500]
                break

        if item.get("cert_number") or item.get("organization"):
            out.append(item)
    return out


def main():
    result = try_api()

    if not result:
        print("[ISO] ОШИБКА: не удалось найти JSON API. Возможные причины:")
        print("  - Изменилась схема API")
        print("  - Сайт блокирует GitHub IP")
        print("  - Нужна авторизация / cookies")
        # Сохраняем пустой файл с error чтобы это было видно в data/
        out = {
            "source": "iso",
            "source_name": "ISO / СУОТ (Госстандарт)",
            "url": BASE + "/#!/certsm/certifs",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "count": 0,
            "error": "API endpoint не найден. Возможно нужно использовать расширение Chrome.",
            "records": [],
        }
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        sys.exit(1)

    records = normalize_records(result["data"])
    print(f"[ISO] Нормализовано: {len(records)}")

    if records:
        print(f"[ISO] Пример записи: {json.dumps(records[0], ensure_ascii=False)[:300]}")

    out = {
        "source": "iso",
        "source_name": "ISO / СУОТ (Госстандарт)",
        "url": result["url"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(records),
        "records": records,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ISO] ✓ Сохранено: {OUT_FILE.stat().st_size // 1024} КБ")


if __name__ == "__main__":
    main()

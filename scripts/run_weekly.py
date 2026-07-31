#!/usr/bin/env python3
"""Локальное еженедельное обновление реестров MAVIS.

Скрипт запускается на рабочем Mac/PC, где белорусские реестры открываются
как у обычного пользователя. Каждый парсер пишет JSON во временное состояние,
после чего данные проходят проверку качества. Плохой/пустой результат никогда
не заменяет последнюю рабочую базу.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "scripts" / "registry_sources.json"
STATUS_PATH = ROOT / "data" / "registry_status.json"
LOG_DIR = ROOT / "logs"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def ratio(records: list[dict[str, Any]], predicate) -> float:
    if not records:
        return 0.0
    return sum(1 for row in records if predicate(row)) / len(records)


def validate_dataset(source: str, data: dict[str, Any] | None, min_count: int, previous_count: int) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not data:
        return False, ["Файл отсутствует или содержит невалидный JSON"]

    records = data.get("records")
    if not isinstance(records, list):
        return False, ["Поле records должно быть массивом"]

    declared = data.get("count")
    if declared != len(records):
        errors.append(f"count={declared}, но фактически записей {len(records)}")

    # Не допускаем внезапное обнуление или резкое падение относительно рабочей базы.
    adaptive_min = min_count
    if previous_count > 0:
        adaptive_min = max(adaptive_min, int(previous_count * 0.60))
    if len(records) < adaptive_min:
        errors.append(f"Слишком мало записей: {len(records)}; требуется не менее {adaptive_min}")

    dict_rows = [row for row in records if isinstance(row, dict)]
    if len(dict_rows) != len(records):
        errors.append("Некоторые записи не являются объектами")
        return False, errors

    org_ratio = ratio(dict_rows, lambda r: bool(str(r.get("organization") or r.get("person") or "").strip()))
    if org_ratio < 0.75:
        errors.append(f"Название организации/ФИО заполнено только у {org_ratio:.0%} записей")

    if source in {"spk", "spk2", "att", "attoff", "iso", "osp", "spec"}:
        cert_ratio = ratio(dict_rows, lambda r: bool(str(r.get("cert_number") or "").strip()))
        if cert_ratio < 0.65:
            errors.append(f"Номер документа заполнен только у {cert_ratio:.0%} записей")

    if source in {"spk", "spk2"}:
        good = ratio(dict_rows, lambda r: bool(re.search(r"\d{4,}.*[-/.]", str(r.get("cert_number") or ""))))
        if good < 0.65:
            errors.append(f"На номер СПК похожи только {good:.0%} записей")

    if source in {"att", "attoff"}:
        good = ratio(dict_rows, lambda r: bool(re.search(r"\d{5,}[-/]?[А-ЯA-Z]{0,4}", str(r.get("cert_number") or ""), re.I)))
        if good < 0.65:
            errors.append(f"На номер аттестата похожи только {good:.0%} записей")
        locations = ratio(dict_rows, lambda r: bool(re.match(r"^(г\.|город|обл\.|область|д\.)", str(r.get("organization") or "").strip(), re.I)))
        if locations > 0.20:
            errors.append(f"У {locations:.0%} записей вместо организации определён адрес/город")

    if source == "spk2":
        placeholder = ratio(dict_rows, lambda r: "технической компетентности" in str(r.get("cert_number") or "").lower())
        if placeholder > 0.01:
            errors.append("В номера документов попал заголовок страницы")

    return not errors, errors


def run_parser(source: str, cfg: dict[str, Any]) -> dict[str, Any]:
    output = ROOT / cfg["output"]
    parser = cfg.get("parser")
    previous = load_json(output)
    previous_count = int((previous or {}).get("count") or 0)
    backup = output.with_suffix(output.suffix + ".last-good")

    if not parser:
        return {
            "source": source,
            "name": cfg["name"],
            "url": cfg["url"],
            "status": "not_implemented",
            "count": previous_count,
            "message": "Коннектор ещё не реализован",
            "attempted_at": utc_now(),
        }

    parser_path = ROOT / parser
    if not parser_path.exists():
        return {
            "source": source,
            "name": cfg["name"],
            "url": cfg["url"],
            "status": "error",
            "count": previous_count,
            "message": f"Не найден файл парсера: {parser}",
            "attempted_at": utc_now(),
        }

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{source}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    if output.exists():
        shutil.copy2(output, backup)

    started = utc_now()
    proc = subprocess.run(
        [sys.executable, str(parser_path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        check=False,
    )
    log_path.write_text(proc.stdout or "", encoding="utf-8")

    candidate = load_json(output)
    valid, errors = validate_dataset(
        source,
        candidate,
        int(cfg.get("min_count") or 1),
        previous_count,
    )

    if proc.returncode != 0:
        errors.insert(0, f"Парсер завершился с кодом {proc.returncode}")
        valid = False

    if not valid:
        if backup.exists():
            os.replace(backup, output)
        elif output.exists():
            output.unlink()
        return {
            "source": source,
            "name": cfg["name"],
            "url": cfg["url"],
            "status": "failed_kept_previous",
            "count": previous_count,
            "message": "; ".join(errors),
            "attempted_at": started,
            "log": str(log_path.relative_to(ROOT)),
        }

    if backup.exists():
        backup.unlink()

    new_count = int((candidate or {}).get("count") or 0)
    return {
        "source": source,
        "name": cfg["name"],
        "url": cfg["url"],
        "status": "updated",
        "count": new_count,
        "previous_count": previous_count,
        "updated_at": (candidate or {}).get("updated_at"),
        "attempted_at": started,
        "log": str(log_path.relative_to(ROOT)),
    }


def git_publish(message: str) -> tuple[bool, str]:
    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)

    if not (ROOT / ".git").exists():
        return False, "Папка не является git-репозиторием. Запускайте скрипт из клонированного GitHub-репозитория."

    add = run(["git", "add", "data"])
    if add.returncode != 0:
        return False, add.stdout.strip()

    diff = run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        return True, "Изменений для публикации нет"

    commit = run(["git", "commit", "-m", message])
    if commit.returncode != 0:
        return False, commit.stdout.strip()

    push = run(["git", "push"])
    return push.returncode == 0, push.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Обновить локальные снимки реестров MAVIS")
    parser.add_argument("--sources", nargs="*", help="ID реестров; по умолчанию все")
    parser.add_argument("--publish", action="store_true", help="После проверки выполнить git commit и git push")
    args = parser.parse_args()

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    selected = args.sources or list(config)
    unknown = [s for s in selected if s not in config]
    if unknown:
        parser.error("Неизвестные источники: " + ", ".join(unknown))

    results: dict[str, Any] = {}
    print("MAVIS Registry Updater")
    print("Корень проекта:", ROOT)
    print("Источники:", ", ".join(selected))

    for source in selected:
        print(f"\n=== {source}: {config[source]['name']} ===")
        result = run_parser(source, config[source])
        results[source] = result
        print(result["status"], "—", result.get("message") or f"{result.get('count', 0)} записей")

    existing_status = load_json(STATUS_PATH) or {}
    existing_sources = existing_status.get("sources") if isinstance(existing_status.get("sources"), dict) else {}
    existing_sources.update(results)
    status_doc = {
        "generated_at": utc_now(),
        "mode": "weekly_local_snapshot",
        "sources": existing_sources,
    }
    atomic_write_json(STATUS_PATH, status_doc)

    updated = [s for s, r in results.items() if r["status"] == "updated"]
    failed = [s for s, r in results.items() if r["status"] == "failed_kept_previous"]
    missing = [s for s, r in results.items() if r["status"] == "not_implemented"]

    print("\n=== ИТОГ ===")
    print("Обновлены:", ", ".join(updated) or "нет")
    print("Сохранена предыдущая база из-за ошибки:", ", ".join(failed) or "нет")
    print("Коннекторы ещё не реализованы:", ", ".join(missing) or "нет")

    if args.publish:
        ok, text = git_publish("Registry snapshot: " + datetime.now().strftime("%Y-%m-%d"))
        print("\nПубликация:", "успешно" if ok else "ошибка")
        print(text)
        if not ok:
            return 2

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

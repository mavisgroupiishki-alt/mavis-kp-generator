import os
import time
import re
from functools import lru_cache
from urllib.parse import quote

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

REGISTRY_BASE_URL = os.getenv(
    "REGISTRY_BASE_URL",
    "https://mavisgroupiishki-alt.github.io/mavis-kp-generator/registry-mvp",
).rstrip("/")
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "30"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))

SOURCE_ORDER = ["spk2", "att", "attoff", "iso", "metal", "osp", "lic"]
SOURCE_LABELS = {
    "spk2": "СПК",
    "att": "Действующие аттестаты",
    "attoff": "Отменённые / прекращённые аттестаты",
    "iso": "ISO / СУОТ",
    "metal": "Сертификаты / декларации продукции",
    "osp": "ОСП / сварочное производство",
    "lic": "Лицензии",
}

_session = requests.Session()
_session.headers.update({"User-Agent": "MAVIS-Registry-Server/1.0"})
_cache = {}


def cache_get(path):
    now = time.time()
    row = _cache.get(path)
    if row and now - row[0] < CACHE_TTL:
        return row[1]
    url = f"{REGISTRY_BASE_URL}/{path}"
    r = _session.get(url, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    _cache[path] = (now, data)
    return data


def normalize_name(value):
    s = str(value or "").lower().replace("ё", "е")
    s = re.sub(r'[«»“”„"\'`]', " ", s)
    s = re.sub(r"[^a-zа-я0-9\s-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    legal_forms = [
        "общество с ограниченной ответственностью",
        "открытое акционерное общество",
        "закрытое акционерное общество",
        "частное унитарное предприятие",
        "совместное общество с ограниченной ответственностью",
        "ооо", "оао", "зао", "чуп", "уп", "сооо", "ип",
    ]
    changed = True
    while changed:
        changed = False
        for form in legal_forms:
            if s == form:
                s = ""
                changed = True
                break
            if s.startswith(form + " "):
                s = s[len(form) + 1 :].strip()
                changed = True
                break
    return s


def fnv_bucket(s):
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return format(h & 15, "x")


def entity_bucket(entity_id):
    return fnv_bucket("e:" + entity_id)


def query_keys(raw):
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) >= 6:
        keys = ["u:" + digits]
        if len(digits) > 6:
            keys.append("u:" + digits[:6])
        return list(dict.fromkeys(keys))

    name = normalize_name(raw)
    if len(name) < 3:
        return []
    keys = []
    for token in [x for x in name.split() if len(x) >= 3][:4]:
        keys.append("n:" + token[: min(6, len(token))])
    return list(dict.fromkeys(keys))


def do_search(raw):
    keys = query_keys(raw)
    if not keys:
        return []

    scores = {}
    by_bucket = {}
    for key in keys:
        by_bucket.setdefault(fnv_bucket(key), []).append(key)

    for bucket, bucket_keys in by_bucket.items():
        shard = cache_get(f"search/{bucket}.json")
        keymap = shard.get("keys", {})
        for key in bucket_keys:
            for entity_id in keymap.get(key, []):
                scores[entity_id] = scores.get(entity_id, 0) + 1

    ids = [x[0] for x in sorted(scores.items(), key=lambda x: -x[1])[:80]]
    if not ids:
        return []

    summaries = []
    by_entity_bucket = {}
    for entity_id in ids:
        by_entity_bucket.setdefault(entity_bucket(entity_id), []).append(entity_id)

    for bucket, wanted in by_entity_bucket.items():
        shard = cache_get(f"directory/{bucket}.json")
        items = shard.get("items", {})
        for entity_id in wanted:
            if entity_id in items:
                summaries.append(items[entity_id])

    digits = re.sub(r"\D", "", raw or "")
    norm = normalize_name(raw)
    tokens = [x for x in norm.split() if x]

    filtered = []
    for item in summaries:
        if len(digits) >= 6:
            if str(item.get("unp") or "").startswith(digits):
                filtered.append(item)
        else:
            nn = normalize_name(item.get("name"))
            if all(token in nn for token in tokens):
                filtered.append(item)

    def sort_key(item):
        unp = str(item.get("unp") or "")
        nn = normalize_name(item.get("name"))
        exact_unp = 0 if digits and unp == digits else 1
        exact_name = 0 if norm and nn == norm else 1
        return (exact_unp, exact_name, len(nn), item.get("name") or "")

    return sorted(filtered, key=sort_key)[:25]


@app.get("/health")
def health():
    try:
        manifest = cache_get("manifest.json")
        return jsonify({
            "ok": True,
            "service": "mavis-registry-server",
            "registry_version": manifest.get("version"),
            "updated_at": manifest.get("updated_at"),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503


@app.route("/install", methods=["GET", "POST"])
def install():
    # Для текущего MVP Bitrix REST пока не используется.
    # Endpoint оставлен для следующего этапа (OAuth/CRM-события).
    return (
        "<html><body style='font-family:Arial;padding:24px'>"
        "<h2>MAVIS — Проверка реестров</h2>"
        "<p>Сервер приложения доступен. Для текущего MVP отдельная OAuth-установка не требуется.</p>"
        "</body></html>"
    )


@app.route("/", methods=["GET", "POST"])
def index():
    return render_template("index.html")


@app.get("/api/manifest")
def manifest():
    try:
        return jsonify(cache_get("manifest.json"))
    except Exception as exc:
        return jsonify({"error": "registry_unavailable", "message": str(exc)}), 502


@app.get("/api/search")
def search():
    raw = (request.args.get("q") or "").strip()
    if not raw:
        return jsonify({"items": [], "message": "Введите УНП или название компании"})
    try:
        return jsonify({"items": do_search(raw)})
    except Exception as exc:
        return jsonify({"error": "registry_unavailable", "message": str(exc)}), 502


@app.get("/api/entity/<entity_id>")
def entity(entity_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,80}", entity_id):
        return jsonify({"error": "bad_entity_id"}), 400
    try:
        shard = cache_get(f"entities/{entity_bucket(entity_id)}.json")
        item = shard.get("items", {}).get(entity_id)
        if not item:
            return jsonify({"error": "not_found"}), 404
        return jsonify(item)
    except Exception as exc:
        return jsonify({"error": "registry_unavailable", "message": str(exc)}), 502


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)

import json
import os
import re
import time
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
_session.headers.update({"User-Agent": "MAVIS-Registry-Server/3.0"})
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


def request_value(name, default=""):
    return (request.form.get(name) or request.args.get(name) or default).strip()


def safe_domain(value):
    value = (value or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9.-]+", value):
        return ""
    return value


def bitrix_call(domain, auth, method, params=None):
    domain = safe_domain(domain)
    if not domain or not auth:
        raise RuntimeError("Нет данных авторизации Bitrix24")
    payload = dict(params or {})
    payload["auth"] = auth
    url = f"https://{domain}/rest/{method}.json"
    r = _session.post(url, json=payload, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(f"{data.get('error')}: {data.get('error_description') or 'Ошибка Bitrix24'}")
    return data.get("result")


def scopes_set():
    raw = request_value("APPLICATION_SCOPE")
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def bind_deal_tab(domain, auth):
    handler = request.url_root.rstrip("/") + "/deal-tab"
    try:
        result = bitrix_call(domain, auth, "placement.bind", {
            "PLACEMENT": "CRM_DEAL_DETAIL_TAB",
            "HANDLER": handler,
            "TITLE": "Проверка реестров",
            "LANG_ALL": {
                "ru": {"TITLE": "Проверка реестров"},
                "en": {"TITLE": "Registry check"},
            },
        })
        return {"ok": True, "state": "bound", "message": "Вкладка «Проверка реестров» подключена к карточкам сделок."}
    except Exception as exc:
        text = str(exc)
        upper = text.upper()
        if "PLACEMENT_MAX_COUNT" in upper or "ALREADY" in upper or "УЖЕ" in upper:
            return {"ok": True, "state": "already", "message": "Вкладка «Проверка реестров» уже подключена."}
        return {"ok": False, "state": "error", "message": text}


def maybe_setup_deal_tab():
    if request.method != "POST":
        return None
    placement = request_value("PLACEMENT")
    # Не пытаемся регистрировать вкладку при открытии самой вкладки.
    if placement == "CRM_DEAL_DETAIL_TAB":
        return None
    auth = request_value("AUTH_ID")
    domain = request_value("DOMAIN")
    if not auth or not domain:
        return None
    scopes = scopes_set()
    missing = [x for x in ("crm", "placement") if scopes and x not in scopes]
    if missing:
        return {
            "ok": False,
            "state": "missing_scope",
            "message": "Для вкладки нужны права приложения: CRM и placement (встройки).",
            "missing": missing,
        }
    return bind_deal_tab(domain, auth)


def get_company_context_from_deal(domain, auth, deal_id):
    deal = bitrix_call(domain, auth, "crm.deal.get", {"id": deal_id}) or {}
    company_id = int(deal.get("COMPANY_ID") or 0)
    deal_title = str(deal.get("TITLE") or "").strip()

    if not company_id:
        return {
            "deal_id": deal_id,
            "deal_title": deal_title,
            "company_id": 0,
            "company_name": deal_title,
            "unp": "",
            "query": deal_title,
            "warning": "К сделке не привязана компания. Поиск выполнен по названию сделки.",
        }

    company = bitrix_call(domain, auth, "crm.company.get", {"id": company_id}) or {}
    company_name = str(company.get("TITLE") or deal_title).strip()

    unp = ""
    try:
        reqs = bitrix_call(domain, auth, "crm.requisite.list", {
            "filter": {"ENTITY_TYPE_ID": 4, "ENTITY_ID": company_id},
            "select": ["ID", "NAME", "RQ_INN", "RQ_COMPANY_NAME", "RQ_COMPANY_FULL_NAME"],
            "order": {"ID": "ASC"},
        }) or []
        for req in reqs:
            candidate = re.sub(r"\D", "", str(req.get("RQ_INN") or ""))
            if candidate:
                unp = candidate
                if len(candidate) == 9:
                    break
    except Exception:
        # Отсутствие/недоступность реквизитов не должно ломать поиск по названию.
        unp = ""

    return {
        "deal_id": deal_id,
        "deal_title": deal_title,
        "company_id": company_id,
        "company_name": company_name,
        "unp": unp,
        "query": unp or company_name,
        "warning": "" if unp else "УНП в реквизитах Bitrix24 не найден — поиск выполнен по названию компании.",
    }


@app.get("/health")
def health():
    try:
        manifest = cache_get("manifest.json")
        return jsonify({
            "ok": True,
            "service": "mavis-registry-server",
            "version": "3.0-deal-tab",
            "registry_version": manifest.get("version"),
            "updated_at": manifest.get("updated_at"),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503


@app.route("/install", methods=["GET", "POST"])
def install():
    setup = maybe_setup_deal_tab()
    return render_template("index.html", bootstrap={"mode": "install", "setup": setup or {}})


@app.route("/", methods=["GET", "POST"])
def index():
    setup = maybe_setup_deal_tab()
    return render_template("index.html", bootstrap={"mode": "main", "setup": setup or {}})


@app.route("/deal-tab", methods=["GET", "POST"])
def deal_tab():
    if request.method != "POST":
        return render_template("index.html", bootstrap={
            "mode": "deal",
            "error": "Эта страница должна открываться из карточки сделки Bitrix24.",
        })

    placement = request_value("PLACEMENT")
    options_raw = request_value("PLACEMENT_OPTIONS", "{}")
    try:
        options = json.loads(options_raw or "{}")
    except Exception:
        options = {}
    deal_id = int(options.get("ID") or 0)
    auth = request_value("AUTH_ID")
    domain = request_value("DOMAIN")

    if placement != "CRM_DEAL_DETAIL_TAB" or deal_id <= 0:
        return render_template("index.html", bootstrap={
            "mode": "deal",
            "error": "Не удалось получить ID текущей сделки из Bitrix24.",
        })

    try:
        ctx = get_company_context_from_deal(domain, auth, deal_id)
        return render_template("index.html", bootstrap={"mode": "deal", "deal": ctx})
    except Exception as exc:
        return render_template("index.html", bootstrap={
            "mode": "deal",
            "error": f"Не удалось получить данные сделки из Bitrix24: {exc}",
        })


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

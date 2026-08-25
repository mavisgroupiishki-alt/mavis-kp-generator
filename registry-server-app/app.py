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
MANIFEST_TTL = int(os.getenv("MANIFEST_TTL", "10"))

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
_session.headers.update({"User-Agent": "MAVIS-Registry-Server/9.0-spk-live-preview"})
_manifest_cache = None
_shard_cache = {}
_spk_document_cache = {}
SPK_BASE_URL = "https://spk.bsc.by"
SPK_CONTENT_ENDPOINT_RE = re.compile(r"^/RegisterDocument/Get[A-Za-z0-9_]+DocumentContent$")
SPK_DOCUMENT_CACHE_TTL = 600


def _get_json(url, params=None):
    r = _session.get(
        url, params=params, timeout=HTTP_TIMEOUT,
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    r.raise_for_status()
    return r.json()


def get_manifest(force=False):
    global _manifest_cache, _shard_cache
    now = time.time()
    if not force and _manifest_cache and now - _manifest_cache[0] < MANIFEST_TTL:
        return _manifest_cache[1]
    url = f"{REGISTRY_BASE_URL}/manifest.json"
    # Query string обходит CDN-кэш GitHub Pages после новой публикации.
    data = _get_json(url, {"cb": f"{int(now)}"})
    old_version = (_manifest_cache[1].get("version") if _manifest_cache else None)
    new_version = data.get("version") or "unknown"
    if old_version and old_version != new_version:
        _shard_cache.clear()
    _manifest_cache = (now, data)
    return data


def cache_get(path):
    if path == "manifest.json":
        return get_manifest()
    manifest = get_manifest()
    version = manifest.get("version") or "unknown"
    key = (version, path)
    now = time.time()
    row = _shard_cache.get(key)
    if row and now - row[0] < CACHE_TTL:
        return row[1]
    url = f"{REGISTRY_BASE_URL}/{path}"
    data = _get_json(url, {"v": version})
    _shard_cache[key] = (now, data)
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
    # Сначала проверяем факт регистрации, а не доверяем APPLICATION_SCOPE из старого POST.
    try:
        placements = bitrix_call(domain, auth, "placement.get", {}) or []
        for row in placements:
            if str(row.get("placement") or "") == "CRM_DEAL_DETAIL_TAB":
                return {
                    "ok": True,
                    "state": "already",
                    "message": "Вкладка «Проверка реестров» уже зарегистрирована в карточках сделок.",
                    "handler": row.get("handler"),
                }
    except Exception:
        # Если placement.get недоступен, всё равно пробуем bind и показываем реальную ошибку API.
        pass

    try:
        bitrix_call(domain, auth, "placement.bind", {
            "PLACEMENT": "CRM_DEAL_DETAIL_TAB",
            "HANDLER": handler,
            "TITLE": "Проверка реестров",
            "LANG_ALL": {
                "ru": {"TITLE": "Проверка реестров"},
                "en": {"TITLE": "Registry check"},
            },
        })
        # Контроль сразу после bind.
        placements = bitrix_call(domain, auth, "placement.get", {}) or []
        found = [x for x in placements if str(x.get("placement") or "") == "CRM_DEAL_DETAIL_TAB"]
        if not found:
            return {
                "ok": False,
                "state": "verify_failed",
                "message": "Bitrix принял placement.bind, но placement.get пока не видит вкладку. Перезагрузите приложение и повторите.",
            }
        return {
            "ok": True,
            "state": "bound",
            "message": "Вкладка «Проверка реестров» зарегистрирована. Полностью перезагрузите страницу Bitrix24 и откройте сделку заново.",
        }
    except Exception as exc:
        text = str(exc)
        upper = text.upper()
        if "PLACEMENT_MAX_COUNT" in upper or "ALREADY" in upper or "УЖЕ" in upper:
            return {"ok": True, "state": "already", "message": "Вкладка «Проверка реестров» уже зарегистрирована."}
        return {"ok": False, "state": "error", "message": f"Не удалось зарегистрировать вкладку: {text}"}


def maybe_setup_deal_tab():
    if request.method != "POST":
        return None
    placement = request_value("PLACEMENT")
    if placement == "CRM_DEAL_DETAIL_TAB":
        return None
    auth = request_value("AUTH_ID")
    domain = request_value("DOMAIN")
    if not auth or not domain:
        return None
    # В v5 специально не блокируем bind по строке APPLICATION_SCOPE:
    # после изменения прав локального приложения она может приходить из старого контекста.
    # Реальное право проверит сам REST placement.get/placement.bind.
    return bind_deal_tab(domain, auth)


def get_company_context_from_deal(domain, auth, deal_id):
    deal = bitrix_call(domain, auth, "crm.deal.get", {"id": deal_id}) or {}
    company_id = int(deal.get("COMPANY_ID") or 0)
    deal_title = str(deal.get("TITLE") or "").strip()
    category_id = int(deal.get("CATEGORY_ID") or 0)
    category_name = ""
    try:
        cat_result = bitrix_call(domain, auth, "crm.category.get", {"entityTypeId": 2, "id": category_id}) or {}
        category = cat_result.get("category") if isinstance(cat_result, dict) else None
        if isinstance(category, dict):
            category_name = str(category.get("name") or "").strip()
    except Exception:
        category_name = ""
    is_sales_funnel = "продаж" in category_name.lower().replace("ё", "е")

    if not company_id:
        return {
            "deal_id": deal_id,
            "deal_title": deal_title,
            "category_id": category_id,
            "category_name": category_name,
            "is_sales_funnel": is_sales_funnel,
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
        "category_id": category_id,
        "category_name": category_name,
        "is_sales_funnel": is_sales_funnel,
        "company_id": company_id,
        "company_name": company_name,
        "unp": unp,
        "query": unp or company_name,
        "warning": "" if unp else "УНП в реквизитах Bitrix24 не найден — поиск выполнен по названию компании.",
    }


@app.get("/health")
def health():
    try:
        manifest = get_manifest(force=True)
        return jsonify({
            "ok": True,
            "service": "mavis-registry-server",
            "version": "10.0-all-funnels",
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
        return jsonify(get_manifest(force=True))
    except Exception as exc:
        return jsonify({"error": "registry_unavailable", "message": str(exc)}), 502


@app.get("/api/search")
def search():
    raw = (request.args.get("q") or "").strip()
    if not raw:
        return jsonify({"items": [], "message": "Введите УНП или название компании"})
    try:
        get_manifest(force=True)
        return jsonify({"items": do_search(raw)})
    except Exception as exc:
        return jsonify({"error": "registry_unavailable", "message": str(exc)}), 502


@app.get("/api/spk-document")
def spk_document():
    raw_id = (request.args.get("id") or "").strip()
    endpoint = (request.args.get("endpoint") or "").strip()
    if not raw_id.isdigit():
        return jsonify({"error": "bad_document_id", "message": "Некорректный ID документа СПК"}), 400
    if not SPK_CONTENT_ENDPOINT_RE.fullmatch(endpoint):
        return jsonify({"error": "bad_endpoint", "message": "Некорректный endpoint документа СПК"}), 400
    doc_id = int(raw_id)
    key = (endpoint, doc_id)
    now = time.time()
    cached = _spk_document_cache.get(key)
    if cached and now - cached[0] < SPK_DOCUMENT_CACHE_TTL:
        return jsonify(cached[1])
    try:
        url = SPK_BASE_URL + endpoint
        r = _session.get(
            url,
            params={"id": doc_id},
            timeout=HTTP_TIMEOUT,
            headers={"Accept": "application/json", "Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        r.raise_for_status()
        payload = r.json()
        if not isinstance(payload, dict):
            raise RuntimeError("СПК вернул неожиданный формат ответа")
        content = payload.get("content")
        title = payload.get("title")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("СПК не вернул содержимое области")
        if len(content) > 3_000_000:
            raise RuntimeError("Документ СПК слишком большой для встроенного просмотра")
        out = {
            "ok": True,
            "document_id": doc_id,
            "title": str(title or "Документ СПК")[:500],
            "content": content,
        }
        _spk_document_cache[key] = (now, out)
        return jsonify(out)
    except Exception as exc:
        return jsonify({"error": "spk_document_unavailable", "message": str(exc)}), 502


@app.get("/api/entity/<entity_id>")
def entity(entity_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,80}", entity_id):
        return jsonify({"error": "bad_entity_id"}), 400
    try:
        get_manifest(force=True)
        shard = cache_get(f"entities/{entity_bucket(entity_id)}.json")
        item = shard.get("items", {}).get(entity_id)
        if not item:
            return jsonify({"error": "not_found"}), 404
        return jsonify(item)
    except Exception as exc:
        return jsonify({"error": "registry_unavailable", "message": str(exc)}), 502


@app.after_request
def no_store_api(response):
    if request.path.startswith("/api/") or request.path == "/health":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import socket
import time
import webbrowser
from dataclasses import asdict
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from pyzotero import zotero

from zotero_cli_agents.config import get_data_dir, load_config, resolve_library_id, resolve_write_credentials
from zotero_cli_agents.core.reader import ZoteroReader
from zotero_cli_agents.core.writer import ZoteroWriteError, ZoteroWriter
from zotero_cli_agents.models import Item

BOOK_ITEM_TYPE = "book"
DEFAULT_TAG = "workflow/book_metadata_update"
GOOGLE_BOOKS_SCOPE = "https://www.googleapis.com/auth/books"
BOOK_EXTRA_FIELDS = ("language", "publisher", "shortTitle", "ISBN", "numPages", "series", "edition", "place")
PLAN_FIELDS = ("title", "date", "abstractNote", "language", "publisher", "ISBN", "numPages")
CSV_FIELDS = (
    "key",
    "status",
    "provider",
    "confidence",
    "changed_fields",
    "tags_to_add",
    "title",
    "candidate_title",
    "old_date",
    "new_date",
    "old_language",
    "new_language",
    "old_publisher",
    "new_publisher",
    "isbn",
    "reason",
)

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
LATIN_RE = re.compile(r"[A-Za-z]")
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
ISBN_RE = re.compile(r"(?:97[89][\-\s]?)?(?:\d[\-\s]?){9}[\dXx]")

DOUBAN_PUBLISHER_MARKERS = (
    "\u51fa\u54c1\u65b9",
    "\u51fa\u7248\u5e74",
    "\u526f\u6807\u9898",
    "\u539f\u4f5c\u540d",
    "\u8bd1\u8005",
    "\u9875\u6570",
    "\u5b9a\u4ef7",
)

MOJIBAKE_REPLACEMENTS = {
    "\u00e2\u20ac\u2122": "'",
    "\u00e2\u20ac\u0153": '"',
    "\u00e2\u20ac\u009d": '"',
    "\u00e2\u20ac\u201d": "-",
    "\u00e2\u20ac\u201c": "-",
}


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = html.unescape(text)
    text = re.sub(r"<\s*br\s*/?\s*>", " ", text, flags=re.IGNORECASE)
    text = TAG_RE.sub(" ", text)
    text = re.sub(r"(?i)([A-Za-z])\u00e2\?\?(s|t|ll|re|ve|d|m)\b", r"\1'\2", text)
    text = text.replace("\u00e2??", "-")
    for old, new in MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(old, new)
    text = (
        text.replace("\u00a0", " ")
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("\t", " ")
        .replace("\u2212", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )
    return SPACE_RE.sub(" ", text).strip()


def clean_publisher(value: Any, library_catalog: str | None = None) -> str:
    text = clean_text(value)
    if not text:
        return ""

    marker_pattern = "|".join(re.escape(marker) for marker in DOUBAN_PUBLISHER_MARKERS)
    if (library_catalog or "").lower() == "douban" or re.search(marker_pattern, text):
        text = re.split(r"\s*(?:" + marker_pattern + r")\s*[:\uff1a]", text, maxsplit=1)[0]
    return clean_text(text)


def normalize_language(value: str | None) -> str:
    raw = clean_text(value).lower()
    if raw in {"zh", "zh-cn", "zh_cn", "cn", "chinese", "chi", "zho"}:
        return "zh"
    if raw in {"en", "eng", "english"}:
        return "en"
    return raw


def infer_language_from_text(*parts: str | None) -> str | None:
    text = " ".join(clean_text(part) for part in parts if part)
    if CJK_RE.search(text):
        return "zh"
    if LATIN_RE.search(text):
        return "en"
    return None


def normalize_book_date(value: str | None) -> str:
    text = clean_text(value)
    if not text:
        return ""

    duplicate_match = re.fullmatch(r"(.+?)\s+\1", text)
    if duplicate_match:
        text = duplicate_match.group(1)

    match = re.fullmatch(r"(\d{4})-00-00(?:\s+\1)?", text)
    if match:
        return match.group(1)
    match = re.fullmatch(r"(\d{4}-\d{2})-00(?:\s+\1)?", text)
    if match:
        return match.group(1)
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\s+\1", text)
    if match:
        return match.group(1)
    match = re.fullmatch(r"(\d{4})\s+\1", text)
    if match:
        return match.group(1)
    match = re.search(r"\b(\d{4}-\d{2}-\d{2}|\d{4}-\d{2}|\d{4})\b", text)
    if match:
        return match.group(1)
    return text


def default_google_oauth_token_cache() -> Path:
    return Path.cwd() / ".zot" / "state" / "google-books-oauth-token.json"


def normalize_isbn(value: str) -> str:
    return re.sub(r"[^0-9Xx]", "", value).upper()


def extract_isbns(value: str | None) -> list[str]:
    found: list[str] = []
    for match in ISBN_RE.findall(value or ""):
        isbn = normalize_isbn(match)
        if len(isbn) in (10, 13) and isbn not in found:
            found.append(isbn)
    return found


def primary_isbn(item: Item) -> str | None:
    isbns = extract_isbns(item.extra.get("ISBN"))
    if not isbns:
        return None
    isbn13 = [isbn for isbn in isbns if len(isbn) == 13]
    return isbn13[-1] if isbn13 else isbns[-1]


def normalize_title_for_match(value: str | None) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return SPACE_RE.sub(" ", text).strip()


def title_similarity(left: str | None, right: str | None) -> float:
    left_norm = normalize_title_for_match(left)
    right_norm = normalize_title_for_match(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm in right_norm or right_norm in left_norm:
        return 1.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def _first_string(values: list[Any] | tuple[Any, ...] | None) -> str | None:
    if not values:
        return None
    value = values[0]
    return clean_text(value) if value is not None else None


def _join_names(values: list[Any] | None) -> str | None:
    if not values:
        return None
    cleaned = [clean_text(value) for value in values if clean_text(value)]
    return "; ".join(cleaned) if cleaned else None


def resolve_google_books(
    session: requests.Session,
    isbn: str,
    api_key: str | None,
    timeout: float,
    access_token: str | None = None,
) -> dict[str, Any]:
    params = {"q": f"isbn:{isbn}", "maxResults": 5, "printType": "books"}
    if api_key:
        params["key"] = api_key
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else None
    response = session.get("https://www.googleapis.com/books/v1/volumes", params=params, headers=headers, timeout=timeout)
    if response.status_code == 429:
        return {"provider": "google_books", "hit": False, "status": 429, "error": "rate_limited"}
    response.raise_for_status()
    payload = response.json()
    items = payload.get("items") or []
    if not items:
        return {"provider": "google_books", "hit": False, "status": response.status_code}
    volume = items[0].get("volumeInfo", {})
    identifiers = [
        normalize_isbn(identifier.get("identifier", ""))
        for identifier in volume.get("industryIdentifiers", []) or []
        if isinstance(identifier, dict)
    ]
    if isbn not in identifiers:
        return {"provider": "google_books", "hit": False, "status": response.status_code, "error": "isbn_mismatch"}

    metadata = {
        "title": clean_text(volume.get("title")),
        "subtitle": clean_text(volume.get("subtitle")),
        "authors": _join_names(volume.get("authors")),
        "publisher": clean_text(volume.get("publisher")),
        "date": normalize_book_date(volume.get("publishedDate")),
        "abstractNote": clean_text(volume.get("description")),
        "language": normalize_language(volume.get("language")),
        "ISBN": " ".join(identifiers),
        "numPages": str(volume.get("pageCount")) if volume.get("pageCount") else "",
        "categories": _join_names(volume.get("categories")),
    }
    return {"provider": "google_books", "hit": True, "status": response.status_code, "metadata": metadata}


def _load_google_oauth_client(client_secret_path: Path) -> dict[str, str]:
    payload = json.loads(client_secret_path.read_text(encoding="utf-8"))
    client = payload.get("installed") or payload.get("web")
    if not isinstance(client, dict):
        raise ValueError("Google OAuth client JSON must contain an 'installed' or 'web' object.")
    required = ("client_id", "client_secret", "auth_uri", "token_uri")
    missing = [key for key in required if not client.get(key)]
    if missing:
        raise ValueError(f"Google OAuth client JSON is missing: {', '.join(missing)}")
    return {key: str(client[key]) for key in required}


def _save_google_token(path: Path, token: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(token, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_google_token(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _token_is_fresh(token: dict[str, Any]) -> bool:
    return bool(token.get("access_token")) and float(token.get("expires_at") or 0) > time.time() + 60


def _refresh_google_token(client: dict[str, str], token: dict[str, Any], token_cache: Path) -> dict[str, Any] | None:
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        return None
    response = requests.post(
        client["token_uri"],
        data={
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if response.status_code >= 400:
        return None
    refreshed = response.json()
    if "access_token" not in refreshed:
        return None
    merged = {**token, **refreshed}
    merged["expires_at"] = time.time() + int(refreshed.get("expires_in", 3600))
    _save_google_token(token_cache, merged)
    return merged


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _authorize_google_token(client: dict[str, str], token_cache: Path, timeout_seconds: int = 300) -> dict[str, Any]:
    port = _free_loopback_port()
    redirect_uri = f"http://localhost:{port}/"
    result: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if query.get("code"):
                result["code"] = query["code"][0]
                body = b"<html><body>Google Books authorization received. You can close this window.</body></html>"
                self.send_response(200)
            else:
                result["error"] = query.get("error", ["missing_code"])[0]
                body = b"<html><body>Authorization failed. Return to the terminal for details.</body></html>"
                self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = HTTPServer(("localhost", port), CallbackHandler)
    server.timeout = timeout_seconds
    auth_url = client["auth_uri"] + "?" + urlencode(
        {
            "client_id": client["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_BOOKS_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
    )
    log("[google-oauth] Opening browser for Google Books authorization.")
    if not webbrowser.open(auth_url):
        log(f"[google-oauth] Open this URL manually: {auth_url}")
    server.handle_request()
    server.server_close()

    if result.get("error"):
        raise RuntimeError(f"Google OAuth authorization failed: {result['error']}")
    if not result.get("code"):
        raise RuntimeError("Google OAuth authorization timed out before receiving a code.")

    response = requests.post(
        client["token_uri"],
        data={
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "code": result["code"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    response.raise_for_status()
    token = response.json()
    if "access_token" not in token:
        raise RuntimeError("Google OAuth token response did not include an access_token.")
    token["expires_at"] = time.time() + int(token.get("expires_in", 3600))
    _save_google_token(token_cache, token)
    return token


def get_google_oauth_access_token(client_secret_path: Path | None, token_cache: Path | None) -> str | None:
    cache_path = token_cache or default_google_oauth_token_cache()
    cached = _load_google_token(cache_path)
    if cached and _token_is_fresh(cached):
        return str(cached["access_token"])
    if client_secret_path is None:
        return None
    client = _load_google_oauth_client(client_secret_path)
    if cached:
        refreshed = _refresh_google_token(client, cached, cache_path)
        if refreshed and _token_is_fresh(refreshed):
            return str(refreshed["access_token"])
    token = _authorize_google_token(client, cache_path)
    return str(token["access_token"])


def resolve_open_library(session: requests.Session, isbn: str, timeout: float) -> dict[str, Any]:
    response = session.get(f"https://openlibrary.org/isbn/{isbn}.json", timeout=timeout)
    if response.status_code == 404:
        return {"provider": "open_library", "hit": False, "status": 404}
    response.raise_for_status()
    payload = response.json()
    metadata = {
        "title": clean_text(payload.get("title")),
        "subtitle": clean_text(payload.get("subtitle")),
        "publisher": _first_string(payload.get("publishers")),
        "date": normalize_book_date(payload.get("publish_date")),
        "ISBN": " ".join(extract_isbns(" ".join((payload.get("isbn_13") or []) + (payload.get("isbn_10") or [])))),
        "numPages": str(payload.get("number_of_pages")) if payload.get("number_of_pages") else "",
        "language": "",
    }
    if payload.get("languages"):
        keys = [str(lang.get("key", "")) for lang in payload.get("languages", []) if isinstance(lang, dict)]
        joined = " ".join(keys).lower()
        if "chinese" in joined:
            metadata["language"] = "zh"
        elif "english" in joined:
            metadata["language"] = "en"
    if not metadata["language"]:
        metadata["language"] = infer_language_from_text(metadata["title"], metadata["publisher"]) or ""
    return {"provider": "open_library", "hit": True, "status": response.status_code, "metadata": metadata}


def resolve_loc(session: requests.Session, isbn: str, timeout: float) -> dict[str, Any]:
    params = {"fo": "json", "fa": f"number_isbn:{isbn}", "c": 5}
    response = session.get("https://www.loc.gov/books/", params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results") or []
    if not results:
        return {"provider": "library_of_congress", "hit": False, "status": response.status_code}
    result = results[0]
    metadata = {
        "title": clean_text(result.get("title")),
        "publisher": _first_string(result.get("publisher") if isinstance(result.get("publisher"), list) else None),
        "date": normalize_book_date(result.get("date")),
        "abstractNote": "",
        "language": infer_language_from_text(result.get("title")) or "",
        "ISBN": isbn,
        "numPages": "",
    }
    return {"provider": "library_of_congress", "hit": True, "status": response.status_code, "metadata": metadata}


def resolve_external_metadata(
    *,
    item: Item,
    providers: list[str],
    google_api_key: str | None,
    google_access_token: str | None,
    timeout: float,
    sleep_seconds: float,
) -> dict[str, Any]:
    isbn = primary_isbn(item)
    if not isbn:
        return {"key": item.key, "isbn": None, "hits": [], "errors": [{"provider": "local", "error": "missing_isbn"}]}

    session = requests.Session()
    hits: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for provider in providers:
        started = time.monotonic()
        try:
            if provider == "google_books":
                result = resolve_google_books(session, isbn, google_api_key, timeout, google_access_token)
            elif provider == "open_library":
                result = resolve_open_library(session, isbn, timeout)
            elif provider == "library_of_congress":
                result = resolve_loc(session, isbn, timeout)
            else:
                errors.append({"provider": provider, "error": "unsupported_provider"})
                continue
            result["latency_ms"] = int((time.monotonic() - started) * 1000)
            if result.get("hit"):
                hits.append(result)
            else:
                errors.append({k: v for k, v in result.items() if k != "metadata"})
        except requests.RequestException as exc:
            errors.append({"provider": provider, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
        except ValueError as exc:
            errors.append({"provider": provider, "error": f"invalid_response: {str(exc)[:200]}"})
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    best = choose_best_hit(item, hits)
    return {"key": item.key, "isbn": isbn, "hits": hits, "errors": errors, "best": best}


def choose_best_hit(item: Item, hits: list[dict[str, Any]]) -> dict[str, Any] | None:
    provider_rank = {"google_books": 3, "open_library": 2, "library_of_congress": 1}
    ranked: list[tuple[float, int, dict[str, Any]]] = []
    for hit in hits:
        metadata = hit.get("metadata") or {}
        similarity = title_similarity(item.title, metadata.get("title"))
        score = similarity + provider_rank.get(str(hit.get("provider")), 0) * 0.05
        ranked.append((score, provider_rank.get(str(hit.get("provider")), 0), hit))
    if not ranked:
        return None
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return ranked[0][2]


def _safe_candidate_fields(item: Item, hit: dict[str, Any]) -> tuple[dict[str, str], str, float]:
    metadata = hit.get("metadata") or {}
    provider = str(hit.get("provider") or "")
    similarity = title_similarity(item.title, metadata.get("title"))
    current_title_has_cjk = bool(CJK_RE.search(item.title))
    candidate_title_has_cjk = bool(CJK_RE.search(str(metadata.get("title") or "")))
    strong_title_match = similarity >= 0.86 or (
        normalize_isbn(metadata.get("ISBN", "")).find(primary_isbn(item) or "NOISBN") >= 0
        and similarity >= 0.70
    )

    fields: dict[str, str] = {}
    reasons: list[str] = []

    if metadata.get("title") and strong_title_match:
        title = clean_text(metadata["title"])
        subtitle = clean_text(metadata.get("subtitle"))
        if subtitle and subtitle.lower() not in title.lower():
            title = f"{title}: {subtitle}"
        if title and title != item.title:
            if provider == "google_books" or not current_title_has_cjk or candidate_title_has_cjk:
                fields["title"] = title
                reasons.append("title_from_isbn_source")

    if metadata.get("date"):
        candidate_date = normalize_book_date(metadata["date"])
        current_date = normalize_book_date(item.date)
        if candidate_date and candidate_date != current_date:
            if provider == "google_books" or current_date[:4] != candidate_date[:4]:
                fields["date"] = candidate_date
                reasons.append("date_from_isbn_source")

    if metadata.get("publisher"):
        publisher = clean_publisher(metadata["publisher"])
        current_publisher = clean_publisher(item.extra.get("publisher"), item.extra.get("libraryCatalog"))
        if publisher and publisher != current_publisher:
            if provider == "google_books" or not current_publisher or len(current_publisher) > 80:
                if CJK_RE.search(current_publisher) and not CJK_RE.search(publisher):
                    pass
                else:
                    fields["publisher"] = publisher
                    reasons.append("publisher_from_isbn_source")

    if metadata.get("abstractNote") and provider == "google_books":
        abstract = clean_text(metadata["abstractNote"])
        current_abstract = clean_text(item.abstract)
        if abstract and abstract != current_abstract and (not current_abstract or len(current_abstract) < 80):
            fields["abstractNote"] = abstract
            reasons.append("description_from_google_books")

    candidate_language = normalize_language(metadata.get("language")) or infer_language_from_text(
        metadata.get("title"), metadata.get("publisher"), metadata.get("abstractNote")
    )
    current_language = normalize_language(item.extra.get("language"))
    if candidate_language and candidate_language != current_language:
        if provider == "google_books" or current_title_has_cjk or candidate_title_has_cjk:
            fields["language"] = candidate_language
            reasons.append("language_from_isbn_source")

    for field_name in ("ISBN", "numPages"):
        candidate_value = clean_text(metadata.get(field_name))
        current_value = clean_text(item.extra.get(field_name))
        if candidate_value and candidate_value != current_value and (provider == "google_books" or not current_value):
            fields[field_name] = candidate_value
            reasons.append(f"{field_name}_from_isbn_source")

    if not strong_title_match and fields:
        # Keep very safe language fixes for obvious Chinese/English mismatch; drop bibliographic overwrites.
        fields = {name: value for name, value in fields.items() if name == "language"}
        reasons = [reason for reason in reasons if reason.startswith("language_")]

    return fields, "; ".join(reasons), similarity


def build_operation_from_resolution(item: Item, resolution: dict[str, Any], add_tag: str | None) -> dict[str, Any]:
    best = resolution.get("best")
    if best:
        fields, reason, similarity = _safe_candidate_fields(item, best)
        provider = str(best.get("provider") or "")
        confidence = round(similarity, 3)
        candidate_title = str((best.get("metadata") or {}).get("title") or "")
    else:
        fields = {}
        reason = "no_external_hit"
        provider = ""
        confidence = 0.0
        candidate_title = ""

    tags_to_add: list[str] = []
    if add_tag and (fields or best) and add_tag not in item.tags:
        tags_to_add.append(add_tag)

    status = "update" if fields else ("resolved_no_field_change" if best else "unresolved")
    return {
        "key": item.key,
        "status": status,
        "title": item.title,
        "candidate_title": candidate_title,
        "provider": provider,
        "confidence": confidence,
        "isbn": resolution.get("isbn"),
        "fields": fields,
        "tags_to_add": tags_to_add,
        "reason": reason,
        "old": {
            "date": item.date,
            "language": item.extra.get("language"),
            "publisher": item.extra.get("publisher"),
            "ISBN": item.extra.get("ISBN"),
            "numPages": item.extra.get("numPages"),
        },
        "new": {
            "date": fields.get("date", item.date),
            "language": fields.get("language", item.extra.get("language")),
            "publisher": fields.get("publisher", item.extra.get("publisher")),
            "ISBN": fields.get("ISBN", item.extra.get("ISBN")),
            "numPages": fields.get("numPages", item.extra.get("numPages")),
        },
        "resolution": resolution,
        "collections": item.collections,
    }


def local_normalization_operation(item: Item, add_tag: str | None = DEFAULT_TAG) -> dict[str, Any] | None:
    fields: dict[str, str] = {}

    _maybe_add_change(fields, "title", item.title, clean_text(item.title))
    if item.abstract is not None:
        _maybe_add_change(fields, "abstractNote", item.abstract, clean_text(item.abstract))

    normalized_date = normalize_book_date(item.date)
    _maybe_add_change(fields, "date", item.date, normalized_date)

    library_catalog = item.extra.get("libraryCatalog")
    for field_name in BOOK_EXTRA_FIELDS:
        current = item.extra.get(field_name)
        if current is None:
            continue
        cleaned = clean_publisher(current, library_catalog) if field_name == "publisher" else clean_text(current)
        _maybe_add_change(fields, field_name, current, cleaned)

    inferred_language = infer_language_from_text(
        fields.get("title", item.title),
        fields.get("abstractNote", item.abstract or ""),
        fields.get("publisher", item.extra.get("publisher", "")),
        fields.get("shortTitle", item.extra.get("shortTitle", "")),
    )
    current_language = normalize_language(item.extra.get("language"))
    if inferred_language and inferred_language != current_language:
        fields["language"] = inferred_language

    tags_to_add: list[str] = []
    if add_tag and add_tag not in item.tags:
        tags_to_add.append(add_tag)

    if not fields and not tags_to_add:
        return None

    return {
        "key": item.key,
        "status": "local_normalization",
        "title": item.title,
        "candidate_title": "",
        "provider": "local",
        "confidence": 1.0,
        "isbn": primary_isbn(item),
        "fields": fields,
        "tags_to_add": tags_to_add,
        "reason": "local_format_normalization",
        "old": {
            "date": item.date,
            "language": item.extra.get("language"),
            "publisher": item.extra.get("publisher"),
        },
        "new": {
            "date": fields.get("date", item.date),
            "language": fields.get("language", item.extra.get("language")),
            "publisher": fields.get("publisher", item.extra.get("publisher")),
        },
        "collections": item.collections,
    }


def _maybe_add_change(fields: dict[str, str], field_name: str, old_value: str | None, new_value: str) -> None:
    old_clean = "" if old_value is None else str(old_value)
    if new_value and new_value != old_clean:
        fields[field_name] = new_value


def build_operation(item: Item, add_tag: str | None = DEFAULT_TAG) -> dict[str, Any] | None:
    """Backward-compatible local normalization hook used by older tests."""
    return local_normalization_operation(item, add_tag=add_tag)


def export_books(profile: str | None, limit: int | None) -> list[Item]:
    cfg = load_config(profile=profile)
    data_dir = get_data_dir(cfg)
    db_path = data_dir / "zotero.sqlite"
    library_id = resolve_library_id(db_path, {"library": "user"})
    reader = ZoteroReader(db_path, library_id=library_id)
    try:
        result = reader.search("", item_type=BOOK_ITEM_TYPE, sort="title", direction="asc", limit=limit or 1_000_000)
        return result.items
    finally:
        reader.close()


def build_plan(
    items: list[Item],
    *,
    add_tag: str | None,
    providers: list[str],
    google_api_key: str | None,
    google_access_token: str | None,
    timeout: float,
    sleep_seconds: float,
    local_normalization: bool,
    progress_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    export_rows = [asdict(item) for item in items]
    operations: list[dict[str, Any]] = []
    resolutions: list[dict[str, Any]] = []
    total = len(items)
    for index, item in enumerate(items, start=1):
        if local_normalization:
            operation = local_normalization_operation(item, add_tag=add_tag)
            resolution = {"key": item.key, "isbn": primary_isbn(item), "hits": [], "errors": [], "best": None}
        else:
            resolution = resolve_external_metadata(
                item=item,
                providers=providers,
                google_api_key=google_api_key,
                google_access_token=google_access_token,
                timeout=timeout,
                sleep_seconds=sleep_seconds,
            )
            operation = build_operation_from_resolution(item, resolution, add_tag)
        resolutions.append(resolution)
        operations.append(operation)
        append_jsonl(
            progress_path,
            {
                "event": "resolved",
                "index": index,
                "total": total,
                "key": item.key,
                "isbn": resolution.get("isbn"),
                "status": operation["status"],
                "provider": operation["provider"],
                "changed_fields": sorted(operation["fields"].keys()),
            },
        )
        log(
            f"[resolve {index}/{total}] {item.key} provider={operation['provider'] or '-'} "
            f"status={operation['status']} fields={','.join(sorted(operation['fields'].keys())) or '-'}"
        )
    return export_rows, operations, resolutions


def operation_to_update_row(operation: dict[str, Any]) -> dict[str, Any] | None:
    fields = operation.get("fields") or {}
    if not fields:
        return None
    return {"key": operation["key"], "fields": fields}


def operation_to_csv_row(operation: dict[str, Any]) -> dict[str, Any]:
    old = operation.get("old", {})
    new = operation.get("new", {})
    return {
        "key": operation["key"],
        "status": operation.get("status", ""),
        "provider": operation.get("provider", ""),
        "confidence": operation.get("confidence", ""),
        "changed_fields": "; ".join(sorted((operation.get("fields") or {}).keys())),
        "tags_to_add": "; ".join(operation.get("tags_to_add") or []),
        "title": operation.get("title", ""),
        "candidate_title": operation.get("candidate_title", ""),
        "old_date": old.get("date") or "",
        "new_date": new.get("date") or "",
        "old_language": old.get("language") or "",
        "new_language": new.get("language") or "",
        "old_publisher": old.get("publisher") or "",
        "new_publisher": new.get("publisher") or "",
        "isbn": operation.get("isbn") or "",
        "reason": operation.get("reason", ""),
    }


def read_completed(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def append_completed(path: Path, key: str) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(key + "\n")


def chunked(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[i : i + size] for i in range(0, len(rows), size)]


def fetch_web_items(zot: zotero.Zotero, keys: list[str]) -> dict[str, dict[str, Any]]:
    fetched: dict[str, dict[str, Any]] = {}
    for batch in [keys[i : i + 50] for i in range(0, len(keys), 50)]:
        if not batch:
            continue
        payloads = zot.items(itemKey=",".join(batch), format="json", include="data", limit=len(batch))
        for payload in payloads:
            data = payload.get("data", payload)
            key = data.get("key")
            if key:
                fetched[str(key)] = data
    return fetched


def verify_operations(
    *,
    operations: list[dict[str, Any]],
    output_dir: Path,
    profile: str | None,
) -> dict[str, Any]:
    cfg = load_config(profile=profile)
    library_id, api_key = resolve_write_credentials(cfg, library_type="user", group_id=None)
    if not library_id or not api_key:
        raise RuntimeError("Zotero Web API credentials are not configured.")

    relevant_operations = [
        operation for operation in operations if operation.get("fields") or operation.get("tags_to_add")
    ]
    zot = zotero.Zotero(library_id, "user", api_key)
    keys = [str(operation["key"]) for operation in relevant_operations]
    fetched = fetch_web_items(zot, keys)

    missing: list[str] = []
    field_mismatches: list[dict[str, Any]] = []
    tag_mismatches: list[dict[str, Any]] = []

    for operation in relevant_operations:
        key = str(operation["key"])
        data = fetched.get(key)
        if data is None:
            missing.append(key)
            continue

        for field_name, expected in (operation.get("fields") or {}).items():
            actual = data.get(field_name)
            if actual != expected:
                field_mismatches.append(
                    {"key": key, "field": field_name, "expected": expected, "actual": actual}
                )

        existing_tags = {tag.get("tag") for tag in data.get("tags", []) if isinstance(tag, dict)}
        for tag in operation.get("tags_to_add") or []:
            if tag not in existing_tags:
                tag_mismatches.append({"key": key, "tag": tag})

    summary = {
        "checked": len(relevant_operations),
        "fetched": len(fetched),
        "missing_count": len(missing),
        "field_mismatch_count": len(field_mismatches),
        "tag_mismatch_count": len(tag_mismatches),
        "missing": missing,
        "field_mismatches": field_mismatches,
        "tag_mismatches": tag_mismatches,
    }
    write_json(output_dir / "book-metadata-web-api-verification.json", summary)
    log(
        "[verify] checked={checked} fetched={fetched} missing={missing_count} "
        "field_mismatches={field_mismatch_count} tag_mismatches={tag_mismatch_count}".format(**summary)
    )
    return summary


def apply_operations(
    *,
    operations: list[dict[str, Any]],
    output_dir: Path,
    batch_size: int,
    resume: bool,
    profile: str | None,
) -> dict[str, Any]:
    cfg = load_config(profile=profile)
    library_id, api_key = resolve_write_credentials(cfg, library_type="user", group_id=None)
    if not library_id or not api_key:
        raise RuntimeError("Zotero Web API credentials are not configured.")

    completed_path = output_dir / "completed-keys.txt"
    failed_path = output_dir / "failed-results.jsonl"
    api_results_path = output_dir / "api-results.ndjson"
    progress_path = output_dir / "progress.ndjson"

    completed = read_completed(completed_path) if resume else set()
    writable_operations = [
        operation for operation in operations if operation.get("fields") or operation.get("tags_to_add")
    ]
    pending = [operation for operation in writable_operations if operation["key"] not in completed]
    batches = chunked(pending, batch_size)
    writer = ZoteroWriter(library_id=library_id, api_key=api_key, library_type="user")
    started = time.monotonic()
    succeeded = 0
    failed = 0

    log(
        f"[apply] writable={len(writable_operations)} pending={len(pending)} "
        f"completed_before={len(completed)}"
    )
    append_jsonl(progress_path, {"event": "apply_start", "total": len(writable_operations), "pending": len(pending)})

    for batch_index, batch in enumerate(batches, start=1):
        for item_index, operation in enumerate(batch, start=1):
            key = str(operation["key"])
            try:
                fields = operation.get("fields") or {}
                tags_to_add = operation.get("tags_to_add") or []
                if fields:
                    writer.update_item(key, fields)
                if tags_to_add:
                    writer.add_tags(key, tags_to_add)
                append_completed(completed_path, key)
                completed.add(key)
                succeeded += 1
                append_jsonl(
                    api_results_path,
                    {"event": "succeeded", "key": key, "fields": fields, "tags_added": tags_to_add},
                )
            except ZoteroWriteError as exc:
                failed += 1
                failure = {
                    "event": "failed",
                    "key": key,
                    "fields": operation.get("fields") or {},
                    "tags_to_add": operation.get("tags_to_add") or [],
                    "error": {"code": exc.code, "message": str(exc), "retryable": exc.retryable},
                }
                append_jsonl(failed_path, failure)
                append_jsonl(api_results_path, failure)

            overall_done = len(completed)
            progress = {
                "event": "progress",
                "batch": batch_index,
                "batch_total": len(batches),
                "item": item_index,
                "batch_size": len(batch),
                "completed": overall_done,
                "total": len(writable_operations),
                "succeeded_this_run": succeeded,
                "failed_this_run": failed,
                "elapsed_seconds": round(time.monotonic() - started, 1),
            }
            append_jsonl(progress_path, progress)
            log(
                f"[batch {batch_index}/{len(batches)}] item {item_index}/{len(batch)} | "
                f"overall {overall_done}/{len(writable_operations)} | succeeded={succeeded} failed={failed}"
            )

    summary = {
        "total_operations": len(operations),
        "writable_operations": len(writable_operations),
        "completed": len(completed),
        "pending_initial": len(pending),
        "succeeded_this_run": succeeded,
        "failed_this_run": failed,
        "elapsed_seconds": round(time.monotonic() - started, 1),
    }
    write_json(output_dir / "book-metadata-apply-summary.json", summary)
    append_jsonl(progress_path, {"event": "apply_complete", **summary})
    return summary


def _parse_providers(value: str) -> list[str]:
    providers = [part.strip() for part in value.split(",") if part.strip()]
    allowed = {"google_books", "open_library", "library_of_congress"}
    unknown = [provider for provider in providers if provider not in allowed]
    if unknown:
        raise argparse.ArgumentTypeError(f"Unsupported provider(s): {', '.join(unknown)}")
    return providers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve and apply Zotero book metadata from external book sources.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--add-tag", default=DEFAULT_TAG)
    parser.add_argument("--no-add-tag", action="store_true")
    parser.add_argument(
        "--providers",
        type=_parse_providers,
        default=_parse_providers("open_library,library_of_congress"),
        help="Comma-separated provider order. Supported: google_books,open_library,library_of_congress.",
    )
    parser.add_argument("--google-api-key", default=os.environ.get("GOOGLE_BOOKS_API_KEY", ""))
    parser.add_argument("--google-oauth-client-secret", type=Path, default=None)
    parser.add_argument("--google-oauth-token-cache", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--sleep-seconds", type=float, default=0.4)
    parser.add_argument(
        "--local-normalization",
        action="store_true",
        help="Use only local text normalization. This is kept for emergency fallback, not the default book workflow.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.batch_size < 1 or args.batch_size > 50:
        raise SystemExit("Batch size must be between 1 and 50.")

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    add_tag = None if args.no_add_tag else args.add_tag
    progress_path = output_dir / "progress.ndjson"

    books = export_books(args.profile, args.limit)
    google_access_token = None
    if "google_books" in args.providers and not args.google_api_key:
        google_access_token = get_google_oauth_access_token(
            args.google_oauth_client_secret,
            args.google_oauth_token_cache,
        )
    export_rows, operations, resolutions = build_plan(
        books,
        add_tag=add_tag,
        providers=args.providers,
        google_api_key=args.google_api_key or None,
        google_access_token=google_access_token,
        timeout=args.timeout,
        sleep_seconds=args.sleep_seconds,
        local_normalization=args.local_normalization,
        progress_path=progress_path,
    )
    update_rows = [row for operation in operations if (row := operation_to_update_row(operation)) is not None]
    csv_rows = [operation_to_csv_row(operation) for operation in operations]
    resolved_count = sum(1 for operation in operations if operation.get("provider"))
    writable_count = sum(1 for operation in operations if operation.get("fields") or operation.get("tags_to_add"))

    write_json(output_dir / "book-metadata-export.json", {"count": len(export_rows), "items": export_rows})
    write_json(output_dir / "book-metadata-resolutions.json", {"count": len(resolutions), "resolutions": resolutions})
    write_json(output_dir / "book-metadata-plan.json", {"count": len(operations), "operations": operations})
    write_jsonl(output_dir / "book-metadata-updates.jsonl", update_rows)
    write_csv(output_dir / "book-metadata-preview.csv", csv_rows)
    write_json(
        output_dir / "book-metadata-dry-run.json",
        {
            "apply": bool(args.apply),
            "book_count": len(books),
            "resolved_count": resolved_count,
            "operation_count": len(operations),
            "writable_operation_count": writable_count,
            "field_update_count": len(update_rows),
            "providers": args.providers,
            "google_api_key_configured": bool(args.google_api_key),
            "google_oauth_configured": bool(args.google_oauth_client_secret or args.google_oauth_token_cache),
            "google_oauth_token_cache": str(args.google_oauth_token_cache or default_google_oauth_token_cache())
            if args.google_oauth_client_secret
            else "",
            "tag": add_tag,
            "output_files": {
                "export": str(output_dir / "book-metadata-export.json"),
                "resolutions": str(output_dir / "book-metadata-resolutions.json"),
                "plan": str(output_dir / "book-metadata-plan.json"),
                "updates_jsonl": str(output_dir / "book-metadata-updates.jsonl"),
                "preview_csv": str(output_dir / "book-metadata-preview.csv"),
            },
        },
    )

    log(
        f"[plan] books={len(books)} resolved={resolved_count} writable={writable_count} "
        f"field_updates={len(update_rows)} providers={','.join(args.providers)}"
    )
    if not args.apply:
        log("[dry-run] No Zotero writes performed. Re-run wrapper with -Apply to write through the Web API.")
        return 0

    summary = apply_operations(
        operations=operations,
        output_dir=output_dir,
        batch_size=args.batch_size,
        resume=args.resume,
        profile=args.profile,
    )
    verification = verify_operations(operations=operations, output_dir=output_dir, profile=args.profile)
    if summary["failed_this_run"]:
        return 2
    if (
        verification["missing_count"]
        or verification["field_mismatch_count"]
        or verification["tag_mismatch_count"]
    ):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

# ruff: noqa: E402,I001

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from email.message import Message
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse

import fitz
import requests

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from zotero_cli_agent.config import get_data_dir, load_config, resolve_write_credentials
from zotero_cli_agent.core.reader import ZoteroReader
from zotero_cli_agent.core.writer import ZoteroWriter
from zotero_cli_agent.models import Attachment, Item


DEFAULT_COLLECTION_KEY = "4NV86WH2"  # 10_STAGE/20_AI on this library at script creation time.
RUNS_DIR = Path(__file__).resolve().parent / "runs"

SUPPORT_TERMS = (
    "supporting information",
    "support information",
    "supplementary information",
    "supplemental information",
    "electronic supplementary information",
)

URL_MARKERS = (
    "suppdata",
    "suppl_file",
    "downloadsupplement",
    "supplement",
    "supporting",
    "suppinfo",
    "supp-info",
    "suppmat",
    "sup-mat",
    "supinfo",
    "supinfo",
    "si_001",
    "_si_",
    "-si-",
    "_sm.",
    "-sm.",
    "mmc",
    "esm",
    "/media",
)

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".zip", ".txt"}
MAX_INLINE_BYTES = 80 * 1024 * 1024


@dataclass
class PdfScan:
    is_supporting: bool
    reason: str = ""
    pages: int | None = None
    error: str = ""


@dataclass
class AttachmentInfo:
    key: str
    filename: str
    content_type: str
    path: str
    exists: bool
    is_pdf: bool
    support_scan: PdfScan | None = None


@dataclass
class CandidateItem:
    key: str
    title: str
    doi: str
    url: str
    publisher: str
    publication_title: str
    pdf_count: int
    attachment_count: int
    existing_pdf_is_supporting: bool
    existing_pdf_reason: str
    attachments: list[AttachmentInfo] = field(default_factory=list)


@dataclass
class ProbeResult:
    url: str
    final_url: str = ""
    ok: bool = False
    status_code: int | None = None
    content_type: str = ""
    filename: str = ""
    size_bytes: int = 0
    is_supporting: bool = False
    reason: str = ""
    error: str = ""
    saved_path: str = ""
    uploaded_key: str = ""


@dataclass
class ItemResult:
    item: CandidateItem
    action: str
    reason: str
    discovered_urls: list[str] = field(default_factory=list)
    probes: list[ProbeResult] = field(default_factory=list)


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        for attr in ("href", "src", "data-href", "data-url", "content"):
            value = values.get(attr)
            if value:
                self.links.append(value)


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def normalize_doi(doi: str) -> str:
    doi = doi.strip()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.I)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.I)
    return doi.strip()


def sanitize_filename(name: str, fallback: str = "download") -> str:
    name = unquote(name).strip().strip('"')
    name = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = fallback
    return name[:180]


def short_title(title: str, max_len: int = 80) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    return title[:max_len]


def has_url_marker(value: str) -> bool:
    lower = value.lower()
    return any(marker in lower for marker in URL_MARKERS)


def has_support_term(value: str) -> bool:
    lower = value.lower()
    return any(term in lower for term in SUPPORT_TERMS)


def scan_pdf_bytes(data: bytes) -> PdfScan:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        pages = len(doc)
        head_parts = []
        for page in doc[: min(3, pages)]:
            head_parts.append(page.get_text("text"))
        text = "\n".join(head_parts)
        doc.close()
    except Exception as exc:
        return PdfScan(False, error=f"{type(exc).__name__}: {exc}")
    return classify_pdf_text(text, pages=pages)


def scan_pdf_path(path: Path, filename: str) -> PdfScan:
    filename_hit = has_support_term(filename) or has_url_marker(filename)
    if filename_hit:
        filename_reason = "filename"
    else:
        filename_reason = ""
    if not path.exists():
        return PdfScan(filename_hit, reason=filename_reason, error="missing_file")
    try:
        doc = fitz.open(path)
        pages = len(doc)
        head_parts = []
        for page in doc[: min(3, pages)]:
            head_parts.append(page.get_text("text"))
        text = "\n".join(head_parts)
        doc.close()
    except Exception as exc:
        return PdfScan(filename_hit, reason=filename_reason, error=f"{type(exc).__name__}: {exc}")
    scan = classify_pdf_text(text, pages=pages)
    if filename_hit and not scan.is_supporting:
        scan.is_supporting = True
        scan.reason = filename_reason
    elif filename_hit and scan.reason:
        scan.reason = f"{filename_reason}+{scan.reason}"
    return scan


def classify_pdf_text(text: str, *, pages: int | None) -> PdfScan:
    collapsed = re.sub(r"\s+", " ", text).strip()
    head = collapsed[:3000].lower()
    very_head = collapsed[:800].lower()

    if re.search(r"^(?:\d+\s*)?(support|supporting|supplementary|supplemental|electronic supplementary)\s+information\b", very_head):
        return PdfScan(True, reason="pdf_heading", pages=pages)
    if "supplementary information (si) for" in head or "supporting information (si) for" in head:
        return PdfScan(True, reason="publisher_si_notice", pages=pages)
    if any(term in very_head for term in SUPPORT_TERMS):
        return PdfScan(True, reason="pdf_head_term", pages=pages)
    if pages is not None and pages <= 8 and any(term in head for term in SUPPORT_TERMS):
        return PdfScan(True, reason="short_pdf_term", pages=pages)
    return PdfScan(False, reason="no_si_signal", pages=pages)


def extension_from_content_type(content_type: str) -> str:
    content_type = content_type.lower().split(";", 1)[0].strip()
    return {
        "application/pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.ms-excel": ".xls",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/zip": ".zip",
        "text/plain": ".txt",
        "text/csv": ".csv",
    }.get(content_type, "")


def parse_content_disposition(value: str) -> str:
    if not value:
        return ""
    msg = Message()
    msg["content-disposition"] = value
    filename = msg.get_filename() or ""
    if filename:
        return filename
    match = re.search(r"filename\*?=(?:UTF-8''|\"?)([^\";]+)", value, flags=re.I)
    return unquote(match.group(1).strip()) if match else ""


def filename_from_url(url: str, content_type: str, content_disposition: str, item_key: str) -> str:
    name = parse_content_disposition(content_disposition)
    if not name:
        path_name = Path(urlparse(url).path).name
        if path_name and "." in path_name:
            name = path_name
    ext = Path(name).suffix.lower()
    if not ext:
        ext = extension_from_content_type(content_type) or ".bin"
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
        name = f"{item_key}_{digest}{ext}"
    return sanitize_filename(name, fallback=f"{item_key}_supporting_info")


def load_attachment_info(att: Attachment) -> AttachmentInfo:
    path = str(att.path) if att.path else ""
    exists = bool(att.path and att.path.exists())
    is_pdf = att.content_type == "application/pdf" or att.filename.lower().endswith(".pdf")
    support_scan = None
    if is_pdf and att.path:
        support_scan = scan_pdf_path(att.path, att.filename)
    return AttachmentInfo(
        key=att.key,
        filename=att.filename,
        content_type=att.content_type,
        path=path,
        exists=exists,
        is_pdf=is_pdf,
        support_scan=support_scan,
    )


def build_candidate_item(reader: ZoteroReader, item: Item) -> CandidateItem | None:
    attachments = reader.get_attachments(item.key)
    attachment_infos = [load_attachment_info(att) for att in attachments]
    pdf_infos = [att for att in attachment_infos if att.is_pdf]
    if len(pdf_infos) not in (0, 1):
        return None
    existing_pdf_is_supporting = False
    existing_pdf_reason = ""
    if len(pdf_infos) == 1 and pdf_infos[0].support_scan:
        existing_pdf_is_supporting = pdf_infos[0].support_scan.is_supporting
        existing_pdf_reason = pdf_infos[0].support_scan.reason or pdf_infos[0].support_scan.error
    return CandidateItem(
        key=item.key,
        title=item.title,
        doi=normalize_doi(item.doi or ""),
        url=item.url or "",
        publisher=item.extra.get("publisher", ""),
        publication_title=item.extra.get("publicationTitle", ""),
        pdf_count=len(pdf_infos),
        attachment_count=len(attachment_infos),
        existing_pdf_is_supporting=existing_pdf_is_supporting,
        existing_pdf_reason=existing_pdf_reason,
        attachments=attachment_infos,
    )


def extract_links(html: str, base_url: str) -> list[str]:
    parser = LinkParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    links = [urljoin(base_url, link.replace("\\/", "/")) for link in parser.links]
    for match in re.finditer(r"https?://[^\"'<>\\\s]+", html):
        links.append(match.group(0).replace("\\/", "/"))
    clean: list[str] = []
    seen: set[str] = set()
    for link in links:
        link = link.strip().rstrip("),.;")
        if not link or link in seen:
            continue
        seen.add(link)
        clean.append(link)
    return clean


def is_probable_file_url(url: str) -> bool:
    lower = unquote(url).lower()
    suffix = Path(urlparse(lower).path).suffix
    return suffix in ALLOWED_EXTENSIONS or has_url_marker(lower)


def add_if_candidate(urls: list[str], url: str) -> None:
    if not url:
        return
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith(("http://", "https://")):
        return
    if is_probable_file_url(url) and url not in urls:
        urls.append(url)


def rsc_urls(doi: str) -> list[str]:
    if not doi.lower().startswith("10.1039/"):
        return []
    code = doi.split("/", 1)[1].lower()
    if len(code) < 4:
        return []
    return [
        f"https://www.rsc.org/suppdata/{code[:2]}/{code[2:4]}/{code}/{code}1.pdf",
        f"https://www.rsc.org/suppdata/{code[:2]}/{code[2:4]}/{code}/{code}.pdf",
    ]


def acs_urls(doi: str) -> list[str]:
    if not doi.lower().startswith("10.1021/"):
        return []
    suffix = doi.split("/", 1)[1].lower()
    journal, _, article = suffix.partition(".")
    prefix_map = {
        "jacs": "ja",
        "acsami": "am",
        "acsenergylett": "nz",
        "acsnano": "nn",
        "acssuschemeng": "sc",
        "acsaem": "ae",
    }
    stems = []
    if journal in prefix_map and article:
        stems.append(f"{prefix_map[journal]}{article}")
    stems.append(suffix.replace(".", ""))
    stems.append(suffix)
    out: list[str] = []
    for stem in dict.fromkeys(stems):
        for index in range(1, 4):
            out.append(f"https://pubs.acs.org/doi/suppl/{doi}/suppl_file/{stem}_si_{index:03d}.pdf")
            out.append(f"https://pubs.acs.org/doi/suppl/{doi}/suppl_file/{stem}_si_{index:03d}.docx")
    return out


def aaas_urls(doi: str) -> list[str]:
    if not doi.lower().startswith("10.1126/"):
        return []
    suffix = doi.split("/", 1)[1].lower()
    return [
        f"https://www.science.org/doi/suppl/{doi}/suppl_file/{suffix}_sm.pdf",
        f"https://www.science.org/doi/suppl/{doi}/suppl_file/{suffix}_sm.docx",
        f"https://www.science.org/doi/suppl/{doi}/suppl_file/{suffix}_supplementary_materials.pdf",
    ]


def elsevier_urls(doi: str, item_url: str, resolved_urls: list[str]) -> list[str]:
    if not doi.lower().startswith("10.1016/"):
        return []
    text = "\n".join([item_url, *resolved_urls])
    piis = re.findall(r"\bS\d{16,18}[A-Z0-9]?\b", text, flags=re.I)
    out: list[str] = []
    for pii in dict.fromkeys(piis):
        for index in range(1, 8):
            for ext in (".pdf", ".docx", ".xlsx", ".zip"):
                out.append(f"https://ars.els-cdn.com/content/image/1-s2.0-{pii}-mmc{index}{ext}")
    return out


def wiley_guess_urls(doi: str) -> list[str]:
    if not doi.lower().startswith("10.1002/"):
        return []
    suffix = doi.split("/", 1)[1].lower()
    stem = suffix.replace(".", "")
    quoted = quote(doi, safe="")
    guesses = [
        f"{stem}-sup-0001-suppinfo.pdf",
        f"{stem}-sup-0001-supplementary_information.pdf",
        f"{stem}-sup-0001-supplementary_material.pdf",
        f"{stem}-sup-0001-misc_information.pdf",
        f"{stem}-sup-0001-supmat.pdf",
    ]
    return [f"https://onlinelibrary.wiley.com/action/downloadSupplement?doi={quoted}&file={file}" for file in guesses]


def iop_media_urls(doi: str) -> list[str]:
    if not doi:
        return []
    if doi.lower().startswith(("10.1088/", "10.1149/")):
        return [f"https://iopscience.iop.org/article/{doi}/media"]
    return []


def publisher_seed_urls(item: CandidateItem, resolved_urls: list[str]) -> list[str]:
    doi = item.doi
    urls: list[str] = []
    for url in (
        *rsc_urls(doi),
        *acs_urls(doi),
        *aaas_urls(doi),
        *elsevier_urls(doi, item.url, resolved_urls),
        *wiley_guess_urls(doi),
        *iop_media_urls(doi),
    ):
        add_if_candidate(urls, url)
    return urls


def fetch_html(session: requests.Session, url: str, timeout: float) -> tuple[str, str, str]:
    try:
        resp = session.get(url, timeout=timeout, allow_redirects=True)
        content_type = resp.headers.get("content-type", "")
        if resp.status_code >= 400:
            return "", resp.url, f"http_{resp.status_code}"
        if "html" not in content_type.lower() and "xml" not in content_type.lower():
            return "", resp.url, f"not_html:{content_type}"
        return resp.text, resp.url, ""
    except Exception as exc:
        return "", url, f"{type(exc).__name__}: {exc}"


def resolve_url(session: requests.Session, url: str, timeout: float) -> str:
    try:
        resp = session.head(url, timeout=min(timeout, 8.0), allow_redirects=True)
        if resp.url:
            return resp.url
    except Exception:
        pass
    try:
        resp = session.get(url, timeout=min(timeout, 8.0), allow_redirects=True, stream=True)
        final_url = resp.url
        resp.close()
        return final_url
    except Exception:
        return url


def discover_urls(session: requests.Session, item: CandidateItem, timeout: float, *, parse_landing: bool) -> list[str]:
    urls: list[str] = []
    landing_pages = []
    if item.url:
        landing_pages.append(item.url)
    if item.doi:
        landing_pages.append(f"https://doi.org/{quote(item.doi, safe='/')}")

    resolved_landing: list[str] = []
    for landing in dict.fromkeys(landing_pages):
        if not parse_landing:
            final_url = resolve_url(session, landing, timeout)
            if final_url:
                resolved_landing.append(final_url)
            continue
        html, final_url, _ = fetch_html(session, landing, min(timeout, 10.0))
        if final_url:
            resolved_landing.append(final_url)
        if html:
            for link in extract_links(html, final_url or landing):
                if has_url_marker(link) or Path(urlparse(link).path).suffix.lower() in ALLOWED_EXTENSIONS:
                    add_if_candidate(urls, link)
    for seeded in publisher_seed_urls(item, resolved_landing):
        add_if_candidate(urls, seeded)
    return list(dict.fromkeys(urls))


def probe_url(
    session: requests.Session,
    url: str,
    item: CandidateItem,
    timeout: float,
    *,
    save_dir: Path | None,
) -> ProbeResult:
    result = ProbeResult(url=url)
    try:
        resp = None
        for attempt in range(2):
            try:
                resp = session.get(url, timeout=timeout, allow_redirects=True)
                break
            except (
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ConnectionError,
                requests.exceptions.ReadTimeout,
            ):
                if attempt == 0:
                    time.sleep(1.0)
                    continue
                raise
        if resp is None:
            result.error = "request_failed"
            return result
        result.final_url = resp.url
        result.status_code = resp.status_code
        result.content_type = resp.headers.get("content-type", "")
        data = resp.content
        result.size_bytes = len(data)
        if resp.status_code >= 400:
            result.error = f"http_{resp.status_code}"
            return result
        if len(data) > MAX_INLINE_BYTES:
            result.error = f"too_large:{len(data)}"
            return result
        filename = filename_from_url(
            resp.url,
            result.content_type,
            resp.headers.get("content-disposition", ""),
            item.key,
        )
        result.filename = filename
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            ext_from_type = extension_from_content_type(result.content_type)
            if ext_from_type:
                filename = sanitize_filename(f"{Path(filename).stem}{ext_from_type}")
                result.filename = filename
                ext = ext_from_type
        if ext not in ALLOWED_EXTENSIONS:
            result.error = f"unsupported_extension:{ext or 'none'}"
            return result
        if "html" in result.content_type.lower():
            result.error = f"html_response:{result.content_type}"
            return result
        url_reason = "url_marker" if has_url_marker(url + " " + resp.url + " " + filename) else ""
        if ext == ".pdf" or result.content_type.lower().startswith("application/pdf"):
            scan = scan_pdf_bytes(data)
            if scan.is_supporting:
                result.is_supporting = True
                result.reason = scan.reason
            elif url_reason:
                result.is_supporting = True
                result.reason = f"{url_reason};pdf:{scan.reason or scan.error}"
            else:
                result.error = f"pdf_not_si:{scan.reason or scan.error}"
                return result
        else:
            if not url_reason and not has_support_term(filename):
                result.error = "non_pdf_without_support_marker"
                return result
            result.is_supporting = True
            result.reason = url_reason or "filename_support_term"
        result.ok = True
        if save_dir is not None:
            save_dir.mkdir(parents=True, exist_ok=True)
            target = unique_path(save_dir / result.filename)
            target.write_bytes(data)
            result.saved_path = str(target)
        return result
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        return result


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    digest = hashlib.sha1(str(time.time()).encode()).hexdigest()[:8]
    return path.with_name(f"{stem}_{digest}{suffix}")


def existing_attachment_names(item: CandidateItem) -> set[str]:
    return {att.filename.lower() for att in item.attachments if att.filename}


def process_item(
    session: requests.Session,
    item: CandidateItem,
    timeout: float,
    run_dir: Path,
    *,
    apply: bool,
    upload: bool,
    writer: ZoteroWriter | None,
    max_probes: int,
    delay: float,
    parse_landing: bool,
) -> ItemResult:
    if item.existing_pdf_is_supporting:
        return ItemResult(item=item, action="skip", reason=f"existing_pdf_is_supporting:{item.existing_pdf_reason}")

    discovered = discover_urls(session, item, timeout, parse_landing=parse_landing)
    result = ItemResult(item=item, action="not_found", reason="no_valid_supporting_info_found", discovered_urls=discovered)
    if not discovered:
        result.reason = "no_candidate_urls"
        return result

    item_save_dir = run_dir / "files" / item.key if apply else None
    attachment_names = existing_attachment_names(item)
    probes_done = 0
    for url in discovered:
        if probes_done >= max_probes:
            result.reason = f"probe_limit_reached:{max_probes}"
            break
        probes_done += 1
        probe = probe_url(session, url, item, timeout, save_dir=item_save_dir)
        result.probes.append(probe)
        probe_host = urlparse(probe.final_url or probe.url).netloc.lower()
        if probe_host.endswith("pubs.acs.org") and probe.error.startswith("http_403"):
            result.action = "not_found"
            result.reason = "host_blocked:pubs.acs.org:http_403"
            break
        if delay:
            time.sleep(delay)
        if not probe.ok:
            continue
        if probe.filename.lower() in attachment_names:
            probe.error = "already_attached_filename"
            probe.ok = False
            continue
        if upload:
            if writer is None:
                probe.error = "writer_not_configured"
                probe.ok = False
                continue
            if not probe.saved_path:
                probe.error = "upload_requires_saved_file"
                probe.ok = False
                continue
            try:
                probe.uploaded_key = writer.upload_attachment(item.key, Path(probe.saved_path))
            except Exception as exc:
                probe.error = f"upload_failed:{type(exc).__name__}: {exc}"
                probe.ok = False
                continue
        result.action = "downloaded_uploaded" if upload else ("downloaded" if apply else "found")
        result.reason = probe.reason or "valid_supporting_info"
        return result
    return result


def make_session(mailto: str) -> requests.Session:
    session = requests.Session()
    user_agent = "zotero-cli-agent-supporting-info-fetcher/0.1"
    if mailto:
        user_agent += f" (mailto:{mailto})"
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "text/html,application/pdf,application/octet-stream;q=0.9,*/*;q=0.7",
        }
    )
    return session


def load_candidates(collection_key: str, only: set[str]) -> list[CandidateItem]:
    cfg = load_config()
    db_path = get_data_dir(cfg) / "zotero.sqlite"
    with ZoteroReader(db_path) as reader:
        items = reader.get_collection_items(collection_key)
        candidates = []
        for item in items:
            if only and item.key not in only:
                continue
            candidate = build_candidate_item(reader, item)
            if candidate is not None:
                candidates.append(candidate)
        return candidates


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def writer_from_config() -> ZoteroWriter:
    cfg = load_config()
    library_id, api_key = resolve_write_credentials(cfg, library_type="user")
    if not library_id or not api_key:
        raise RuntimeError("Zotero write credentials are missing")
    return ZoteroWriter(library_id=library_id, api_key=api_key, library_type="user")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch supporting information for 20_AI candidate Zotero items.")
    parser.add_argument("--collection-key", default=DEFAULT_COLLECTION_KEY)
    parser.add_argument("--only", action="append", default=[], help="Process only this item key; may be repeated.")
    parser.add_argument("--apply", action="store_true", help="Save downloaded supporting files under AA/runs.")
    parser.add_argument("--upload", action="store_true", help="Upload saved files to Zotero Web API. Requires --apply.")
    parser.add_argument("--max-items", type=int, default=0, help="Process at most N candidate items.")
    parser.add_argument("--max-probes", type=int, default=12, help="Maximum candidate URLs to probe per item.")
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--delay", type=float, default=0.25, help="Delay between candidate downloads.")
    parser.add_argument("--parse-landing", action="store_true", help="Also parse publisher landing pages for links.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.upload and not args.apply:
        raise SystemExit("--upload requires --apply")

    cfg = load_config()
    run_dir = RUNS_DIR / f"supporting-info-{now_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    session = make_session(cfg.crossref_mailto)
    only = set(args.only)
    candidates = load_candidates(args.collection_key, only)
    if args.max_items:
        candidates = candidates[: args.max_items]

    writer = writer_from_config() if args.upload else None
    results: list[ItemResult] = []
    ledger = run_dir / "results.jsonl"
    for index, candidate in enumerate(candidates, start=1):
        print(
            f"[{index}/{len(candidates)}] {candidate.key} pdfs={candidate.pdf_count} "
            f"doi={candidate.doi} title={short_title(candidate.title)}",
            flush=True,
        )
        result = process_item(
            session,
            candidate,
            args.timeout,
            run_dir,
            apply=args.apply,
            upload=args.upload,
            writer=writer,
            max_probes=args.max_probes,
            delay=args.delay,
            parse_landing=args.parse_landing,
        )
        results.append(result)
        with ledger.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
        print(f"  -> {result.action}: {result.reason}", flush=True)

    summary: dict[str, Any] = {
        "collection_key": args.collection_key,
        "apply": args.apply,
        "upload": args.upload,
        "candidate_count": len(candidates),
        "counts": {},
        "run_dir": str(run_dir),
    }
    for result in results:
        summary["counts"][result.action] = summary["counts"].get(result.action, 0) + 1
    write_json(run_dir / "summary.json", summary)
    write_json(run_dir / "candidates.json", [asdict(candidate) for candidate in candidates])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

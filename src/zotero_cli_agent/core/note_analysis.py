from __future__ import annotations

import json
from collections.abc import Callable

from zotero_cli_agent.core.ai_client import AiClient
from zotero_cli_agent.core.note_renderer import render_note
from zotero_cli_agent.core.note_templates import format_template, load_template
from zotero_cli_agent.core.rag import clean_html, convert_pdfs_to_text, infer_pdf_kind
from zotero_cli_agent.core.reader import ZoteroReader
from zotero_cli_agent.core.writer import ZoteroWriter
from zotero_cli_agent.models import Item

ANALYZED_TAG = "ai_analyzed"
NOT_ANALYZED_TAG = "ai_not_analyzed"
NOTE_TITLE_PREFIX = "AI条目分析 - "

_CLASSIFY_CHARS = 4000
_BOOK_ITEM_TYPES = {"book", "bookSection"}
_TEMPLATE_BY_TYPE = {
    "research_article": "research-article",
    "review_article": "review-article",
    "book": "book",
}

_FENCE = chr(96) * 3  # markdown code fence (three backticks)

_MIN_SECTIONS = 10

_PARSE_RETRY_SUFFIX = (
    "\n\n【输出格式要求（必须遵守）】"
    "上一次输出无法解析为 JSON。请重新输出，且只输出一个 json 代码块："
    "不要输出任何解释文字，顶层必须是 {\"sections\": [...]}，"
    "确保 JSON 完整闭合（花括号、引号全部配对），字符串内换行用 \\n 转义。"
)

_SPARSE_RETRY_SUFFIX = (
    "\n\n【内容充实度要求（必须遵守）】"
    "上一次输出过于简略。请重新生成完整分析：每个章节内容充实具体，"
    "关键结论带证据锚点（页码/图号/表号/文献编号）与具体数值；"
    "笔记原子化每类至少 3 条并带 citations；优缺点至少 3 条优点、2 条缺点；"
    "研究启发至少 3 条；论证逻辑链路图用固定表格且至少 5 行。"
    "仍只输出一个 json 代码块。"
)


class NoteAnalysisError(Exception):
    def __init__(self, message: str, *, code: str = "runtime_error", retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _item_authors(item: Item) -> str:
    return ", ".join(c.full_name for c in item.creators)


def _item_journal(item: Item) -> str:
    return str(item.extra.get("publicationTitle") or item.extra.get("journalAbbreviation") or "")


def extract_json_object(text: str) -> dict:
    s = text.strip()
    lines = s.split("\n")
    if lines and lines[0].lstrip().startswith(_FENCE):
        lines = lines[1:]
    if lines and lines[-1].strip() == _FENCE:
        lines = lines[:-1]
    s = "\n".join(lines).strip()

    candidates = [s]
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end > start:
        candidates.insert(0, s[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    raise NoteAnalysisError("无法从 AI 输出中解析出 JSON")


def _chat(ai_client: AiClient, prompt: str) -> str:
    try:
        return ai_client.chat(prompt)
    except NoteAnalysisError:
        raise
    except Exception as e:
        raise NoteAnalysisError(
            f"AI 调用失败：{type(e).__name__}: {e}", code="network_error", retryable=True
        ) from e


def _classify(
    item: Item,
    sample_text: str,
    ai_client: AiClient,
    progress: Callable[[str, str], None] | None,
) -> str:
    if item.item_type in _BOOK_ITEM_TYPES:
        return "book"
    if progress:
        progress("classify", f"item_type={item.item_type}")
    template = load_template("classify-item")
    prompt = (
        template
        + "\n\n## 待判定的条目\n\n"
        + f"标题：{item.title}\n"
        + f"摘要：{item.abstract or ''}\n"
        + f"正文开头：\n{sample_text}\n"
    )
    answer = _chat(ai_client, prompt)
    data = extract_json_object(answer)
    return str(data.get("paper_type", "")).strip() or "uncertain"


def analyze_item(
    reader: ZoteroReader,
    writer: ZoteroWriter,
    ai_client: AiClient,
    key: str,
    *,
    force: bool = False,
    no_tag: bool = False,
    extractor: str = "mineru",
    dry_run: bool = False,
    progress: Callable[[str, str], None] | None = None,
) -> dict:
    item = reader.get_item(key)
    if item is None:
        raise NoteAnalysisError(f"条目 '{key}' 不存在", code="not_found")

    if ANALYZED_TAG in item.tags and not force:
        return {"status": "already_analyzed", "item_key": key, "item_type": item.item_type}

    attachments = reader.get_pdf_attachments(key)
    if not attachments:
        raise NoteAnalysisError(f"条目 '{key}' 没有本地 PDF 附件", code="validation_error")

    pdf_paths = [a.path for a in attachments if a.path is not None and a.path.exists()]
    if not pdf_paths:
        raise NoteAnalysisError(f"条目 '{key}' 的 PDF 附件文件不存在", code="validation_error")

    if progress:
        progress("extract", f"{len(pdf_paths)} PDF(s)")
    pdf_texts = convert_pdfs_to_text(pdf_paths, extractor)

    main_parts: list[str] = []
    supp_parts: list[str] = []
    for att in attachments:
        if att.path is None or att.path not in pdf_texts:
            continue
        text = pdf_texts[att.path]
        if isinstance(text, Exception) or not text or not text.strip():
            continue
        kind = infer_pdf_kind(text, att.filename or att.key)
        if kind == "supplementary":
            supp_parts.append(text)
        else:
            main_parts.append(text)

    main_text = "\n\n".join(main_parts)
    if not main_text.strip():
        raise NoteAnalysisError(f"条目 '{key}' 的 PDF 抽取结果为空", code="runtime_error")

    full_text = main_text
    if supp_parts:
        full_text += "\n\n## 支撑信息\n\n" + "\n\n".join(supp_parts)

    paper_type = _classify(item, main_text[:_CLASSIFY_CHARS], ai_client, progress)
    if paper_type == "uncertain":
        if not no_tag:
            writer.add_tags(key, [NOT_ANALYZED_TAG])
        return {"status": "uncertain", "item_key": key, "paper_type": paper_type}
    if paper_type not in _TEMPLATE_BY_TYPE:
        paper_type = "research_article"

    cleaned = clean_html(full_text)
    max_chars = ai_client.config.max_extracted_chars
    if max_chars > 0 and len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]

    template_name = _TEMPLATE_BY_TYPE[paper_type]
    template = load_template(template_name)
    prompt = format_template(
        template,
        title=item.title,
        authors=_item_authors(item),
        journal=_item_journal(item),
        date=item.date or "",
        doi=item.doi or "",
        fulltext=cleaned,
    )

    if dry_run:
        return {
            "status": "dry_run",
            "item_key": key,
            "item_type": item.item_type,
            "paper_type": paper_type,
            "template": template_name,
            "pdf_count": len(pdf_paths),
            "chars": len(cleaned),
            "prompt_preview": prompt[:1200],
        }

    if progress:
        progress("analyze", f"paper_type={paper_type}")
    answer = _chat(ai_client, prompt)
    try:
        sections = extract_json_object(answer).get("sections", [])
    except NoteAnalysisError:
        if progress:
            progress("retry", "AI 输出无法解析为 JSON，追加格式要求重试一次")
        retry_answer = _chat(ai_client, prompt + _PARSE_RETRY_SUFFIX)
        try:
            sections = extract_json_object(retry_answer).get("sections", [])
        except NoteAnalysisError as retry_error:
            snippet = retry_answer[:300].replace("\n", " ")
            raise NoteAnalysisError(
                f"AI 输出两次都无法解析为 JSON（响应开头：{snippet}...）",
                code="runtime_error",
            ) from retry_error
    if not isinstance(sections, list):
        sections = []
    if len(sections) < _MIN_SECTIONS:
        if progress:
            progress("retry", f"输出过简略（{len(sections)} 个 block），追加内容充实度要求重试一次")
        try:
            retry_answer = _chat(ai_client, prompt + _SPARSE_RETRY_SUFFIX)
            retried = extract_json_object(retry_answer).get("sections", [])
            if isinstance(retried, list) and len(retried) > len(sections):
                sections = retried
        except NoteAnalysisError:
            pass

    note_title = NOTE_TITLE_PREFIX + item.title
    html_note = render_note(sections, title=note_title)
    note_key = writer.add_note(key, html_note)
    if not no_tag:
        writer.add_tags(key, [ANALYZED_TAG])

    return {
        "status": "ok",
        "item_key": key,
        "note_key": note_key,
        "paper_type": paper_type,
        "sections": len(sections),
    }

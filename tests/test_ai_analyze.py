"""Tests for the AI note analysis pipeline and CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from zotero_cli_agent.cli import main
from zotero_cli_agent.config import AiNoteConfig
from zotero_cli_agent.core.ai_client import AiClient
from zotero_cli_agent.core.note_analysis import (
    ANALYZED_TAG,
    NOT_ANALYZED_TAG,
    NoteAnalysisError,
    analyze_item,
    extract_json_object,
)
from zotero_cli_agent.models import Attachment, Creator, Item

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _make_item(item_type="journalArticle", tags=None, abstract="摘要内容") -> Item:
    return Item(
        key="ABC123",
        item_type=item_type,
        title="Test Paper",
        creators=[Creator("Alice", "Smith", "author")],
        abstract=abstract,
        date="2024",
        url=None,
        doi="10.1234/test",
        tags=tags or [],
        collections=[],
        date_added="2024-01-01",
        date_modified="2024-01-01",
        extra={"publicationTitle": "Nature"},
    )


def _make_attachment(tmp_path) -> Attachment:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    return Attachment(
        key="ATT1",
        parent_key="ABC123",
        filename="paper.pdf",
        content_type="application/pdf",
        path=pdf,
    )


def _make_ai_config() -> AiNoteConfig:
    return AiNoteConfig(api_key="k", base_url="http://x", model="m", max_extracted_chars=10000)


def _sections_json(n: int = 12) -> str:
    return json.dumps(
        {"sections": [{"type": "paragraph", "text": f"内容 {i}"} for i in range(n)]},
        ensure_ascii=False,
    )


class TestExtractJsonObject:
    def test_fenced_json(self):
        fence = chr(96) * 3
        text = fence + "json\n" + '{"sections": []}' + "\n" + fence
        assert extract_json_object(text) == {"sections": []}

    def test_bare_json(self):
        assert extract_json_object('{"a": 1}') == {"a": 1}

    def test_json_with_extra_text(self):
        text = '分析结果如下：\n{"sections": []}\n完毕'
        assert extract_json_object(text) == {"sections": []}

    def test_invalid_raises(self):
        with pytest.raises(NoteAnalysisError):
            extract_json_object("没有任何 json")


class TestAnalyzeItem:
    def test_analyze_research_article(self, tmp_path):
        item = _make_item()
        att = _make_attachment(tmp_path)
        reader = MagicMock()
        reader.get_item.return_value = item
        reader.get_pdf_attachments.return_value = [att]

        writer = MagicMock()
        writer.add_note.return_value = "NOTE1"

        ai_client = MagicMock()
        ai_client.config = _make_ai_config()
        ai_client.chat.side_effect = [
            '{"paper_type":"research_article","confidence":0.9,"evidence":["e"],"reason":"r"}',
            _sections_json(12),
        ]

        with patch(
            "zotero_cli_agent.core.note_analysis.convert_pdfs_to_text",
            return_value={att.path: "Introduction. This is the main text."},
        ):
            result = analyze_item(reader, writer, ai_client, "ABC123")

        assert result["status"] == "ok"
        assert result["paper_type"] == "research_article"
        assert result["note_key"] == "NOTE1"
        assert ai_client.chat.call_count == 2  # classify + analyze
        writer.add_note.assert_called_once()
        writer.add_tags.assert_called_once_with("ABC123", [ANALYZED_TAG])

    def test_analyze_book_prejudged_by_item_type(self, tmp_path):
        item = _make_item(item_type="book")
        att = _make_attachment(tmp_path)
        reader = MagicMock()
        reader.get_item.return_value = item
        reader.get_pdf_attachments.return_value = [att]

        writer = MagicMock()
        writer.add_note.return_value = "NOTE1"

        ai_client = MagicMock()
        ai_client.config = _make_ai_config()
        ai_client.chat.return_value = _sections_json(12)

        with patch(
            "zotero_cli_agent.core.note_analysis.convert_pdfs_to_text",
            return_value={att.path: "Chapter 1. Introduction."},
        ):
            result = analyze_item(reader, writer, ai_client, "ABC123")

        assert result["paper_type"] == "book"
        assert ai_client.chat.call_count == 1  # no classification call for book

    def test_analyze_uncertain_skips_and_tags(self, tmp_path):
        item = _make_item()
        att = _make_attachment(tmp_path)
        reader = MagicMock()
        reader.get_item.return_value = item
        reader.get_pdf_attachments.return_value = [att]

        writer = MagicMock()
        ai_client = MagicMock()
        ai_client.config = _make_ai_config()
        ai_client.chat.return_value = '{"paper_type":"uncertain","confidence":0.4,"evidence":["e"],"reason":"r"}'

        with patch(
            "zotero_cli_agent.core.note_analysis.convert_pdfs_to_text",
            return_value={att.path: "Some text."},
        ):
            result = analyze_item(reader, writer, ai_client, "ABC123")

        assert result["status"] == "uncertain"
        writer.add_note.assert_not_called()
        writer.add_tags.assert_called_once_with("ABC123", [NOT_ANALYZED_TAG])

    def test_analyze_already_analyzed(self):
        item = _make_item(tags=[ANALYZED_TAG])
        reader = MagicMock()
        reader.get_item.return_value = item
        writer = MagicMock()
        ai_client = MagicMock()

        result = analyze_item(reader, writer, ai_client, "ABC123")
        assert result["status"] == "already_analyzed"
        writer.add_note.assert_not_called()

    def test_analyze_force_reruns(self, tmp_path):
        item = _make_item(tags=[ANALYZED_TAG])
        att = _make_attachment(tmp_path)
        reader = MagicMock()
        reader.get_item.return_value = item
        reader.get_pdf_attachments.return_value = [att]
        writer = MagicMock()
        writer.add_note.return_value = "NOTE2"
        ai_client = MagicMock()
        ai_client.config = _make_ai_config()
        ai_client.chat.side_effect = [
            '{"paper_type":"research_article","confidence":0.9,"evidence":["e"],"reason":"r"}',
            _sections_json(12),
        ]

        with patch(
            "zotero_cli_agent.core.note_analysis.convert_pdfs_to_text",
            return_value={att.path: "text"},
        ):
            result = analyze_item(reader, writer, ai_client, "ABC123", force=True)

        assert result["status"] == "ok"

    def test_analyze_dry_run(self, tmp_path):
        item = _make_item()
        att = _make_attachment(tmp_path)
        reader = MagicMock()
        reader.get_item.return_value = item
        reader.get_pdf_attachments.return_value = [att]
        writer = MagicMock()
        ai_client = MagicMock()
        ai_client.config = _make_ai_config()
        ai_client.chat.side_effect = [
            '{"paper_type":"research_article","confidence":0.9,"evidence":["e"],"reason":"r"}',
        ]

        with patch(
            "zotero_cli_agent.core.note_analysis.convert_pdfs_to_text",
            return_value={att.path: "Introduction text."},
        ):
            result = analyze_item(reader, writer, ai_client, "ABC123", dry_run=True)

        assert result["status"] == "dry_run"
        assert result["paper_type"] == "research_article"
        assert result["template"] == "research-article"
        writer.add_note.assert_not_called()

    def test_analyze_sparse_output_retries(self, tmp_path):
        item = _make_item()
        att = _make_attachment(tmp_path)
        reader = MagicMock()
        reader.get_item.return_value = item
        reader.get_pdf_attachments.return_value = [att]
        writer = MagicMock()
        writer.add_note.return_value = "NOTE1"
        ai_client = MagicMock()
        ai_client.config = _make_ai_config()
        ai_client.chat.side_effect = [
            '{"paper_type":"research_article","confidence":0.9,"evidence":["e"],"reason":"r"}',
            _sections_json(3),
            _sections_json(15),
        ]

        with patch(
            "zotero_cli_agent.core.note_analysis.convert_pdfs_to_text",
            return_value={att.path: "Introduction text."},
        ):
            result = analyze_item(reader, writer, ai_client, "ABC123")

        assert result["status"] == "ok"
        assert result["sections"] == 15
        assert ai_client.chat.call_count == 3  # classify + analyze + retry
        writer.add_note.assert_called_once()

    def test_analyze_sparse_retry_keeps_better_of_two(self, tmp_path):
        item = _make_item()
        att = _make_attachment(tmp_path)
        reader = MagicMock()
        reader.get_item.return_value = item
        reader.get_pdf_attachments.return_value = [att]
        writer = MagicMock()
        writer.add_note.return_value = "NOTE1"
        ai_client = MagicMock()
        ai_client.config = _make_ai_config()
        ai_client.chat.side_effect = [
            '{"paper_type":"research_article","confidence":0.9,"evidence":["e"],"reason":"r"}',
            _sections_json(3),
            _sections_json(2),
        ]

        with patch(
            "zotero_cli_agent.core.note_analysis.convert_pdfs_to_text",
            return_value={att.path: "Introduction text."},
        ):
            result = analyze_item(reader, writer, ai_client, "ABC123")

        assert result["status"] == "ok"
        assert result["sections"] == 3
        assert ai_client.chat.call_count == 3


class TestAiClient:
    @staticmethod
    def _respond(content: str = "{}"):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    def test_chat_sends_system_prompt_and_temperature(self):
        config = _make_ai_config()
        client = AiClient(config)
        client._client.chat.completions.create = MagicMock(return_value=self._respond())
        out = client.chat("hello")
        assert out == "{}"
        kwargs = client._client.chat.completions.create.call_args.kwargs
        assert kwargs["model"] == config.model
        assert kwargs["messages"][0]["role"] == "system"
        assert "科研文献分析" in kwargs["messages"][0]["content"]
        assert kwargs["messages"][1] == {"role": "user", "content": "hello"}
        assert kwargs["temperature"] == 0.7
        assert "max_tokens" not in kwargs

    def test_chat_passes_max_tokens_when_configured(self):
        config = _make_ai_config()
        config.max_tokens = 16384
        client = AiClient(config)
        client._client.chat.completions.create = MagicMock(return_value=self._respond())
        client.chat("hello")
        kwargs = client._client.chat.completions.create.call_args.kwargs
        assert kwargs["max_tokens"] == 16384


class TestAiAnalyzeCLI:
    def _run(self, args, env=None):
        runner = CliRunner()
        base_env = {
            "ZOT_DATA_DIR": str(FIXTURES_DIR),
            "ZOT_LIBRARY_ID": "123",
            "ZOT_API_KEY": "abc",
            "ZOT_FORMAT": "",
        }
        if env:
            base_env.update(env)
        return runner.invoke(main, args, env=base_env)

    def test_dry_run_envelope(self):
        result = {
            "status": "dry_run",
            "item_key": "ABC123",
            "item_type": "journalArticle",
            "paper_type": "research_article",
            "template": "research-article",
            "pdf_count": 1,
            "chars": 100,
            "prompt_preview": "preview",
        }
        with patch("zotero_cli_agent.commands.ai_analyze.analyze_item", return_value=result), patch(
            "zotero_cli_agent.commands.ai_analyze.ZoteroReader"
        ), patch("zotero_cli_agent.commands.ai_analyze.ZoteroWriter"), patch(
            "zotero_cli_agent.commands.ai_analyze.AiClient"
        ):
            res = self._run(["ai_analyze", "ABC123", "--dry-run"])

        assert res.exit_code == 0
        data = json.loads(res.output)["data"]
        assert data["status"] == "dry_run"
        assert data["paper_type"] == "research_article"

    def test_not_found_error_exit_code(self):
        with patch(
            "zotero_cli_agent.commands.ai_analyze.analyze_item",
            side_effect=NoteAnalysisError("条目 'X' 不存在", code="not_found"),
        ), patch("zotero_cli_agent.commands.ai_analyze.ZoteroReader"), patch(
            "zotero_cli_agent.commands.ai_analyze.ZoteroWriter"
        ), patch("zotero_cli_agent.commands.ai_analyze.AiClient"):
            res = self._run(["ai_analyze", "X"])

        assert res.exit_code == 4
        env = json.loads(res.output)
        assert env["error"]["code"] == "not_found"

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from book_metadata_cleanup import (  # noqa: E402
    build_operation,
    build_operation_from_resolution,
    clean_publisher,
    clean_text,
    extract_isbns,
    get_google_oauth_access_token,
    normalize_book_date,
    resolve_google_books,
    resolve_open_library,
)

from zotero_cli_agents.models import Item  # noqa: E402


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"unexpected HTTP status: {self.status_code}")


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests: list[tuple[str, dict | None]] = []

    def get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        timeout: float | None = None,
    ) -> FakeResponse:
        self.requests.append((url, params))
        return self.response


def _item(
    *,
    key: str = "BOOK001",
    title: str = "Test",
    abstract: str | None = None,
    date: str | None = None,
    tags: list[str] | None = None,
    extra: dict[str, str] | None = None,
) -> Item:
    return Item(
        key=key,
        item_type="book",
        title=title,
        creators=[],
        abstract=abstract,
        date=date,
        url=None,
        doi=None,
        tags=tags or [],
        collections=[],
        date_added="2024-01-01",
        date_modified="2024-01-02",
        extra=extra or {},
    )


def test_clean_publisher_extracts_douban_html_publisher() -> None:
    raw = (
        '<a href="https://book.douban.com/press/2806">'
        "\u6c11\u4e3b\u4e0e\u5efa\u8bbe\u51fa\u7248\u793e</a>"
        ' <br> <span class="pl">\u51fa\u54c1\u65b9:</span>'
        ' <a href="x">\u822a\u4e00\u6587\u5316</a>'
    )

    assert clean_publisher(raw, "Douban") == "\u6c11\u4e3b\u4e0e\u5efa\u8bbe\u51fa\u7248\u793e"


def test_normalize_book_date_removes_zero_month_day_and_duplicates() -> None:
    assert normalize_book_date("2016-00-00 2016") == "2016"
    assert normalize_book_date("2018-02-00 2018-02") == "2018-02"
    assert normalize_book_date("2021-07-10 2021-07-10") == "2021-07-10"


def test_extract_isbns_prefers_clean_tokens() -> None:
    assert extract_isbns("978-7-03-046874-1 0-471-04372-9") == ["9787030468741", "0471043729"]


def test_build_operation_infers_chinese_language_and_date_cleanup() -> None:
    item = _item(
        title="\u6df1\u5165\u6d45\u51fa pandas\uff1a\u5229\u7528 python \u8fdb\u884c\u6570\u636e\u5904\u7406",
        date="2021-07-10 2021-07-10",
        extra={"language": "en", "publisher": "\u673a\u68b0\u5de5\u4e1a\u51fa\u7248\u793e", "libraryCatalog": "Douban"},
    )

    operation = build_operation(item, add_tag=None)

    assert operation is not None
    assert operation["fields"]["date"] == "2021-07-10"
    assert operation["fields"]["language"] == "zh"


def test_build_operation_returns_tag_only_when_fields_are_clean() -> None:
    item = _item(title="Deep Learning", date="2016", tags=[], extra={"language": "en", "publisher": "MIT Press"})

    operation = build_operation(item, add_tag="workflow/book_metadata_cleaned")

    assert operation is not None
    assert operation["fields"] == {}
    assert operation["tags_to_add"] == ["workflow/book_metadata_cleaned"]


def test_clean_text_fixes_basic_html_whitespace_and_mojibake() -> None:
    assert clean_text("<p>Python\u00e2??s&nbsp;best\u00e2??and neglected\u00e2??features</p>\n") == (
        "Python's best-and neglected-features"
    )


def test_resolve_google_books_maps_volume_metadata() -> None:
    session = FakeSession(
        FakeResponse(
            {
                "totalItems": 1,
                "items": [
                    {
                        "volumeInfo": {
                            "title": "Deep Learning",
                            "authors": ["Ian Goodfellow"],
                            "publisher": "MIT Press",
                            "publishedDate": "2016",
                            "description": "<p>Neural networks</p>",
                            "language": "en",
                            "pageCount": 800,
                            "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780262035613"}],
                        }
                    }
                ],
            }
        )
    )

    result = resolve_google_books(session, "9780262035613", None, 1)

    assert result["hit"] is True
    assert result["metadata"]["title"] == "Deep Learning"
    assert result["metadata"]["publisher"] == "MIT Press"
    assert result["metadata"]["numPages"] == "800"


def test_resolve_open_library_maps_isbn_record() -> None:
    session = FakeSession(
        FakeResponse(
            {
                "title": "Electrochemical methods",
                "publishers": ["Wiley"],
                "publish_date": "2001",
                "isbn_13": ["9780471043720"],
                "number_of_pages": 833,
                "languages": [{"key": "/languages/eng"}],
            }
        )
    )

    result = resolve_open_library(session, "9780471043720", 1)

    assert result["hit"] is True
    assert result["metadata"]["publisher"] == "Wiley"
    assert result["metadata"]["language"] == "en"


def test_external_resolution_builds_safe_operation_from_google() -> None:
    item = _item(
        title="Electrochemical methods: fundamentals and applications",
        date="1983",
        extra={"ISBN": "978-0-471-04372-0", "language": "en", "publisher": "American Chemical Society (ACS)"},
    )
    resolution = {
        "key": item.key,
        "isbn": "9780471043720",
        "best": {
            "provider": "google_books",
            "metadata": {
                "title": "Electrochemical methods",
                "date": "2001",
                "publisher": "Wiley",
                "language": "en",
                "ISBN": "9780471043720",
                "numPages": "833",
            },
        },
        "hits": [],
        "errors": [],
    }

    operation = build_operation_from_resolution(item, resolution, add_tag="workflow/metadata")

    assert operation["provider"] == "google_books"
    assert operation["fields"]["date"] == "2001"
    assert operation["fields"]["publisher"] == "Wiley"
    assert operation["fields"]["numPages"] == "833"
    assert operation["tags_to_add"] == ["workflow/metadata"]


def test_external_resolution_adds_only_single_workflow_tag() -> None:
    item = _item(
        title="Deep Learning",
        date="2016",
        extra={"ISBN": "9780262035613", "language": "en", "publisher": "MIT Press"},
    )
    resolution = {
        "key": item.key,
        "isbn": "9780262035613",
        "best": {
            "provider": "google_books",
            "metadata": {"title": "Deep Learning", "date": "2016", "publisher": "MIT Press"},
        },
        "hits": [],
        "errors": [],
    }

    operation = build_operation_from_resolution(item, resolution, add_tag="workflow/metadata")

    assert operation["tags_to_add"] == ["workflow/metadata"]


def test_external_resolution_drops_bibliographic_fields_when_title_conflicts() -> None:
    item = _item(
        title="Deep Learning",
        date="2016",
        extra={"ISBN": "9780262035613", "language": "en", "publisher": "MIT Press"},
    )
    resolution = {
        "key": item.key,
        "isbn": "9780262035613",
        "best": {
            "provider": "open_library",
            "metadata": {"title": "Completely unrelated", "date": "1999", "publisher": "Other"},
        },
        "hits": [],
        "errors": [],
    }

    operation = build_operation_from_resolution(item, resolution, add_tag=None)

    assert operation["fields"] == {}


def test_external_resolution_keeps_chinese_publisher_against_latin_transliteration() -> None:
    item = _item(
        title="\u6587\u57ce",
        date="2021-03-00 2021-03",
        extra={"ISBN": "9787530221099", "language": "zh", "publisher": "\u5317\u4eac\u5341\u6708\u6587\u827a\u51fa\u7248\u793e"},
    )
    resolution = {
        "key": item.key,
        "isbn": "9787530221099",
        "best": {
            "provider": "google_books",
            "metadata": {"title": "\u6587\u57ce", "date": "2021-03-01", "publisher": "Bei Jing Shi Yue Wen Yi Chu Ban She"},
        },
        "hits": [],
        "errors": [],
    }

    operation = build_operation_from_resolution(item, resolution, add_tag=None)

    assert "publisher" not in operation["fields"]


def test_google_oauth_uses_fresh_cached_access_token_without_client_secret(tmp_path: Path) -> None:
    token_cache = tmp_path / "google-books-oauth-token.json"
    token_cache.write_text(
        '{"access_token":"cached-token","expires_at":4102444800,"refresh_token":"refresh-token"}',
        encoding="utf-8",
    )

    assert get_google_oauth_access_token(None, token_cache) == "cached-token"


@pytest.mark.parametrize("provider", ["crossref", "isbn_db"])
def test_provider_parser_rejects_crossref_and_unknown(provider: str) -> None:
    import argparse

    from book_metadata_cleanup import _parse_providers

    with pytest.raises(argparse.ArgumentTypeError):
        _parse_providers(provider)

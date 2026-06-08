import json

from zotero_cli_workflows import import_rss_build_zotero_items as workflow


class DummyWriter:
    def __init__(self) -> None:
        self._counter = 0
        self.created_items = []

    def create_collection(self, name, parent_key=None):
        self._counter += 1
        return f"C{self._counter}"

    def add_journal_article(self, *, doi=None, url=None, extra_fields=None):
        self.created_items.append({"doi": doi, "url": url, "extra_fields": extra_fields})
        return "ITEM1"

    def move_to_collection(self, item_key, collection_key):
        return None


def test_import_records_unexpected_entry_exception(tmp_path, monkeypatch):
    import_list = tmp_path / "import_list.json"
    import_list.write_text(
        json.dumps(
            {
                "root_collection": "00_INBOX",
                "entries": [
                    {
                        "item_id": "doi:10.1234/example",
                        "doi": "10.1234/example",
                        "url": "https://example.org/paper",
                        "title": "Example paper",
                        "journal": "Example Journal",
                        "target_collections": ["00_INBOX/00_UNSORTED"],
                        "tracked_authors": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(workflow, "_build_client", lambda *args, **kwargs: object())
    monkeypatch.setattr(workflow, "_load_local_collection_paths", lambda *args, **kwargs: {})
    monkeypatch.setattr(workflow, "_build_server_collection_maps", lambda client: ({}, {}))
    monkeypatch.setattr(
        workflow,
        "_collect_import_server_state",
        lambda **kwargs: ({}, {"collections": []}, None),
    )
    monkeypatch.setattr(workflow, "_build_writer", lambda *args, **kwargs: DummyWriter())
    monkeypatch.setattr(
        workflow,
        "_resolve_metadata",
        lambda doi: (_ for _ in ()).throw(RuntimeError("metadata lookup failed")),
    )

    output_dir = tmp_path / "out"
    summary = workflow.import_rss_zotero_items(
        import_list=import_list,
        output_dir=output_dir,
        profile=None,
        library="user",
        limit=None,
        apply=True,
        recent_cutoff_utc=None,
    )

    assert summary["failed"] == 1
    assert summary["created_new"] == 0
    failed = json.loads((output_dir / "failed_results.json").read_text(encoding="utf-8"))
    assert failed[0]["item_id"] == "doi:10.1234/example"
    assert failed[0]["doi"] == "10.1234/example"
    assert failed[0]["url"] == "https://example.org/paper"
    assert failed[0]["error"]["code"] == "unexpected_exception"
    assert failed[0]["error"]["type"] == "RuntimeError"


def test_build_list_includes_url_only_journal_items(tmp_path):
    selected_json = tmp_path / "selected.json"
    selected_json.write_text(
        json.dumps(
            [
                {
                    "entry_uid": "A",
                    "doi": None,
                    "title": "URL only paper",
                    "journal": "Example Journal",
                    "abstract": "RSS abstract",
                    "source": {
                        "link": "https://example.org/paper/",
                        "published_at": "2026-06-08T03:36:20+08:00",
                    },
                    "tags": ["alert_type:keyword"],
                },
                {
                    "entry_uid": "B",
                    "doi": "10.1234/example",
                    "title": "DOI paper",
                    "journal": "DOI Journal",
                    "source": {"link": "https://example.org/doi-paper"},
                    "tags": ["alert_type:author", "tracked_author:Jane Doe"],
                },
            ]
        ),
        encoding="utf-8",
    )
    summary = workflow.build_rss_zotero_items_outputs(
        selected_json=selected_json,
        output_dir=tmp_path / "out",
        repo_root=tmp_path,
        zotero_export_json=None,
        skip_library_export=True,
    )

    assert summary["skipped_library_export"] is True
    assert summary["zotero_export_json"] is None
    assert summary["total_selected_rows"] == 2
    assert summary["selected_rows_with_doi"] == 1
    assert summary["selected_rows_without_doi"] == 1
    assert summary["unique_selected_items"] == 2
    assert summary["unique_items_without_doi"] == 1
    assert summary["new_items"] == 2
    assert "new_dois" not in summary

    import_list = json.loads((tmp_path / "out" / "import_list.json").read_text(encoding="utf-8"))
    url_only = next(row for row in import_list["entries"] if row["doi"] is None)
    assert url_only["item_id"] == "url:https://example.org/paper"
    assert url_only["url"] == "https://example.org/paper"
    assert url_only["journal"] == "Example Journal"
    assert url_only["abstract"] == "RSS abstract"
    assert url_only["date"] == "2026-06-08"
    assert url_only["target_collections"] == ["00_INBOX/00_UNSORTED"]
    assert "tags" not in url_only


def test_import_url_only_entry_as_journal_article(tmp_path, monkeypatch):
    import_list = tmp_path / "import_list.json"
    import_list.write_text(
        json.dumps(
            {
                "root_collection": "00_INBOX",
                "entries": [
                    {
                        "item_id": "url:https://example.org/paper",
                        "doi": None,
                        "url": "https://example.org/paper",
                        "title": "URL only paper",
                        "journal": "Example Journal",
                        "abstract": "RSS abstract",
                        "date": "2026-06-08",
                        "target_collections": ["00_INBOX/00_UNSORTED"],
                        "tracked_authors": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    writer = DummyWriter()
    monkeypatch.setattr(workflow, "_build_client", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        workflow,
        "_load_local_collection_paths",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("local DB should be skipped")),
    )
    monkeypatch.setattr(workflow, "_build_server_collection_maps", lambda client: ({}, {}))
    monkeypatch.setattr(
        workflow,
        "_collect_import_server_state",
        lambda **kwargs: ({}, {"collections": []}, None),
    )
    monkeypatch.setattr(workflow, "_build_writer", lambda *args, **kwargs: writer)
    monkeypatch.setattr(
        workflow,
        "_resolve_metadata",
        lambda doi: (_ for _ in ()).throw(AssertionError("URL-only entries must not resolve DOI metadata")),
    )

    summary = workflow.import_rss_zotero_items(
        import_list=import_list,
        output_dir=tmp_path / "out",
        profile=None,
        library="user",
        limit=None,
        apply=True,
        recent_cutoff_utc=None,
        skip_local_db=True,
    )

    assert summary["created_new"] == 1
    assert summary["failed"] == 0
    assert writer.created_items == [
        {
            "doi": None,
            "url": "https://example.org/paper",
            "extra_fields": {
                "title": "URL only paper",
                "publicationTitle": "Example Journal",
                "abstractNote": "RSS abstract",
                "date": "2026-06-08",
                "url": "https://example.org/paper",
            },
        }
    ]
    assert "tags" not in writer.created_items[0]["extra_fields"]

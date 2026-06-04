import json

from zotero_cli_workflows import import_rss_doi_route_plan as workflow


class DummyWriter:
    def __init__(self) -> None:
        self._counter = 0

    def create_collection(self, name, parent_key=None):
        self._counter += 1
        return f"C{self._counter}"

    def add_item(self, doi, extra_fields=None):
        return "ITEM1"

    def move_to_collection(self, item_key, collection_key):
        return None


def test_import_records_unexpected_entry_exception(tmp_path, monkeypatch):
    route_plan = tmp_path / "route_plan.json"
    route_plan.write_text(
        json.dumps(
            {
                "root_collection": "00_INBOX",
                "entries": [
                    {
                        "doi": "10.1234/example",
                        "title": "Example paper",
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
        "_collect_route_server_state",
        lambda **kwargs: ({}, {"collections": []}, None),
    )
    monkeypatch.setattr(workflow, "_build_writer", lambda *args, **kwargs: DummyWriter())
    monkeypatch.setattr(
        workflow,
        "_resolve_metadata",
        lambda doi: (_ for _ in ()).throw(RuntimeError("metadata lookup failed")),
    )

    output_dir = tmp_path / "out"
    summary = workflow.import_rss_doi_route_plan(
        route_plan=route_plan,
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
    assert failed[0]["doi"] == "10.1234/example"
    assert failed[0]["error"]["code"] == "unexpected_exception"
    assert failed[0]["error"]["type"] == "RuntimeError"

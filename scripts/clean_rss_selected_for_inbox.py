from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT_COLLECTION_NAME = "00_INBOX_AA"


@dataclass
class ManifestRow:
    doi: str
    title: str
    journal: str | None
    entry_uids: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    tracked_authors: list[str] = field(default_factory=list)
    source_links: list[str] = field(default_factory=list)

    def merge_entry(self, entry: dict[str, Any]) -> None:
        self.entry_uids.extend(_as_unique_strings([entry.get("entry_uid")], self.entry_uids))
        self.topics.extend(_as_unique_strings([entry.get("topic")], self.topics))
        self.keywords.extend(_as_unique_strings(entry.get("keywords") or [], self.keywords))
        self.tags.extend(_as_unique_strings(entry.get("tags") or [], self.tags))
        self.tracked_authors.extend(_as_unique_strings(_extract_tracked_authors(entry.get("tags") or []), self.tracked_authors))
        self.source_links.extend(_as_unique_strings([_nested_get(entry, "source", "link")], self.source_links))

    @property
    def alert_type(self) -> str:
        return "author" if self.tracked_authors else "general"

    @property
    def target_collections(self) -> list[str]:
        if not self.tracked_authors:
            return [ROOT_COLLECTION_NAME]
        targets = [ROOT_COLLECTION_NAME]
        targets.extend(f"{ROOT_COLLECTION_NAME}/{author}" for author in self.tracked_authors)
        return targets

    def to_manifest_dict(self, *, already_in_library: bool) -> dict[str, Any]:
        return {
            "doi": self.doi,
            "title": self.title,
            "journal": self.journal,
            "alert_type": self.alert_type,
            "tracked_authors": self.tracked_authors,
            "target_collections": self.target_collections,
            "already_in_library": already_in_library,
            "entry_uids": self.entry_uids,
            "topics": self.topics,
            "keywords": self.keywords,
            "tags": self.tags,
            "source_links": self.source_links,
        }


def _nested_get(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _normalize_doi(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return text.lower()


def _normalize_author_name(raw: str) -> str:
    return " ".join(raw.strip().split())


def _extract_tracked_authors(tags: list[Any]) -> list[str]:
    authors: list[str] = []
    has_author_alert = any(str(tag).strip() == "alert_type:author" for tag in tags)
    for tag in tags:
        text = str(tag).strip()
        if text.startswith("tracked_author:"):
            name = _normalize_author_name(text.split(":", 1)[1])
            if name and name not in authors:
                authors.append(name)
    if not authors and has_author_alert:
        for tag in tags:
            text = str(tag).strip()
            if text.startswith("alert_key:"):
                name = _normalize_author_name(text.split(":", 1)[1])
                if name and name not in authors:
                    authors.append(name)
    return authors


def _as_unique_strings(values: list[Any], existing: list[str]) -> list[str]:
    existing_set = set(existing)
    out: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in existing_set:
            continue
        existing_set.add(text)
        out.append(text)
    return out


def _load_selected_items(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a top-level JSON array in {path}")
    items: list[dict[str, Any]] = []
    for row in payload:
        if isinstance(row, dict):
            items.append(row)
    return items


def _build_manifest(items: list[dict[str, Any]]) -> dict[str, ManifestRow]:
    manifest: dict[str, ManifestRow] = {}
    for entry in items:
        doi = _normalize_doi(entry.get("doi"))
        if doi is None:
            continue
        row = manifest.get(doi)
        if row is None:
            row = ManifestRow(
                doi=doi,
                title=str(entry.get("title") or "").strip(),
                journal=(str(entry.get("journal")).strip() if entry.get("journal") else None),
            )
            manifest[doi] = row
        row.merge_entry(entry)
    return manifest


def _load_library_dois_from_export(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        raise ValueError(f"Expected export JSON to contain a list under 'data': {path}")
    dois: set[str] = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        doi = _normalize_doi(row.get("doi"))
        if doi:
            dois.add(doi)
    return dois


def _export_current_library(repo_root: Path, export_path: Path) -> None:
    cmd = ["uv", "run", "zot", "--json", "--detail", "full", "summarize-all"]
    result = subprocess.run(
        cmd,
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Failed to export current Zotero library via summarize-all.\n"
            f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
        )
    export_path.write_text(result.stdout, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def build_outputs(
    *,
    selected_json: Path,
    output_dir: Path,
    repo_root: Path,
    zotero_export_json: Path | None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    export_path = zotero_export_json or output_dir / "zotero_before.json"
    if zotero_export_json is None:
        _export_current_library(repo_root, export_path)

    selected_items = _load_selected_items(selected_json)
    manifest = _build_manifest(selected_items)
    library_dois = _load_library_dois_from_export(export_path)

    manifest_rows: list[dict[str, Any]] = []
    new_manifest_rows: list[dict[str, Any]] = []
    root_only_dois: list[str] = []
    author_routes: dict[str, list[str]] = defaultdict(list)

    for doi in sorted(manifest):
        row = manifest[doi]
        already_in_library = doi in library_dois
        row_dict = row.to_manifest_dict(already_in_library=already_in_library)
        manifest_rows.append(row_dict)
        if already_in_library:
            continue
        new_manifest_rows.append(row_dict)
        if row.tracked_authors:
            for author in row.tracked_authors:
                author_routes[author].append(doi)
        else:
            root_only_dois.append(doi)

    doi_manifest_path = output_dir / "doi_manifest.json"
    new_manifest_path = output_dir / "new_doi_manifest.json"
    new_dois_path = output_dir / "new_dois.txt"
    route_plan_path = output_dir / "route_plan.json"
    summary_path = output_dir / "summary.json"

    _write_json(doi_manifest_path, manifest_rows)
    _write_json(new_manifest_path, new_manifest_rows)
    new_dois_path.write_text("\n".join(row["doi"] for row in new_manifest_rows) + ("\n" if new_manifest_rows else ""), encoding="utf-8")

    route_plan = {
        "root_collection": ROOT_COLLECTION_NAME,
        "root_only_dois": root_only_dois,
        "author_collections": [
            {
                "author": author,
                "collection_path": [ROOT_COLLECTION_NAME, author],
                "dois": sorted(dois),
            }
            for author, dois in sorted(author_routes.items())
        ],
        "entries": new_manifest_rows,
    }
    _write_json(route_plan_path, route_plan)

    summary = {
        "selected_json": str(selected_json),
        "zotero_export_json": str(export_path),
        "total_selected_rows": len(selected_items),
        "unique_selected_dois": len(manifest_rows),
        "already_in_library": len(manifest_rows) - len(new_manifest_rows),
        "new_dois": len(new_manifest_rows),
        "root_only_new_dois": len(root_only_dois),
        "author_routed_new_dois": sum(len(dois) for dois in author_routes.values()),
        "author_collection_count": len(author_routes),
        "output_files": {
            "doi_manifest": str(doi_manifest_path),
            "new_doi_manifest": str(new_manifest_path),
            "new_dois": str(new_dois_path),
            "route_plan": str(route_plan_path),
            "summary": str(summary_path),
        },
    }
    _write_json(summary_path, summary)
    return summary


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Clean RSS selected items into a DOI-only inbox import plan for zotero-cli-agents."
    )
    parser.add_argument("--selected-json", type=Path, required=True, help="Path to the RSS selected JSON array.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=repo_root / "tmp" / "rss_inbox_plan",
        help="Directory for generated plan files.",
    )
    parser.add_argument(
        "--zotero-export-json",
        type=Path,
        default=None,
        help="Optional existing summarize-all JSON export. If omitted, the script runs 'uv run zot --json --detail full summarize-all'.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    summary = build_outputs(
        selected_json=args.selected_json.resolve(),
        output_dir=args.output_dir.resolve(),
        repo_root=repo_root,
        zotero_export_json=(args.zotero_export_json.resolve() if args.zotero_export_json else None),
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

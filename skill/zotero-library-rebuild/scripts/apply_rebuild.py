from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pyzotero import zotero
from pyzotero.zotero_errors import PyZoteroError, ResourceNotFoundError

from zotero_cli_agents.config import load_config, project_root, resolve_write_credentials

API_TIMEOUT = 300.0
DEFAULT_BATCH_SIZE = 25
T = TypeVar("T")


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def chunks(values: list[T], size: int) -> Iterable[list[T]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def short_error(exc: BaseException) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)}


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def resolve_review_dir(raw_review_dir: str) -> Path:
    root = project_root()
    log_root = (root / "log").resolve()
    raw_path = Path(raw_review_dir)
    if raw_path.is_absolute():
        review_dir = raw_path.resolve()
    elif raw_path.parts and raw_path.parts[0].lower() == "log":
        review_dir = (root / raw_path).resolve()
    else:
        review_dir = (log_root / "zotero-library-rebuild" / raw_path).resolve()

    if review_dir == log_root or log_root not in review_dir.parents:
        raise SystemExit(f"Review directory must be under repository log directory: {log_root}")
    return review_dir


def default_output_dir(review_dir: Path) -> Path:
    return review_dir / "50_execution_results" / f"apply-{now_stamp()}"


def build_client(profile: str | None) -> zotero.Zotero:
    cfg = load_config(profile=profile)
    library_id, api_key = resolve_write_credentials(cfg, library_type="user")
    if not library_id or not api_key:
        raise RuntimeError("Zotero write credentials are missing. Run 'zot config init' or fill .zot/config.toml.")
    client = zotero.Zotero(str(library_id), "user", api_key)
    if client.client is not None:
        client.client.timeout = httpx.Timeout(API_TIMEOUT)
    return client


def collection_key(collection: dict[str, Any]) -> str:
    return str(collection.get("key") or collection.get("data", {}).get("key"))


def collection_name(collection: dict[str, Any]) -> str:
    return str(collection.get("data", {}).get("name") or collection.get("name"))


def collection_parent(collection: dict[str, Any]) -> str | None:
    value = collection.get("data", {}).get("parentCollection")
    return str(value) if value else None


def fetch_collection_state(client: zotero.Zotero) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    collections = client.all_collections()
    by_key = {collection_key(coll): coll for coll in collections}
    path_cache: dict[str, str] = {}

    def path_for(key: str) -> str:
        if key in path_cache:
            return path_cache[key]
        coll = by_key[key]
        parent_key = collection_parent(coll)
        if parent_key and parent_key in by_key:
            path = f"{path_for(parent_key)}/{collection_name(coll)}"
        else:
            path = collection_name(coll)
        path_cache[key] = path
        return path

    path_to_key = {path_for(key): key for key in by_key}
    return path_to_key, by_key


def create_collection(client: zotero.Zotero, name: str, parent_key: str | None) -> str:
    response = client.create_collections([{"name": name, "parentCollection": parent_key or False}])
    successful = response.get("successful", {})
    if "0" in successful:
        return str(successful["0"]["key"])
    failed = response.get("failed", {})
    if failed:
        message = failed.get("0", {}).get("message", "unknown collection create failure")
        raise RuntimeError(message)
    raise RuntimeError(f"Unexpected collection create response: {response}")


def ensure_collection_path(
    *,
    client: zotero.Zotero,
    path_to_key: dict[str, str],
    collection_path: str,
    apply: bool,
    output_dir: Path,
    created_counter: Counter[str],
) -> str:
    if collection_path in path_to_key:
        return path_to_key[collection_path]

    parts = [part for part in collection_path.split("/") if part]
    current_parts: list[str] = []
    parent_key: str | None = None
    for part in parts:
        current_parts.append(part)
        path = "/".join(current_parts)
        if path in path_to_key:
            parent_key = path_to_key[path]
            continue

        if apply:
            key = create_collection(client, part, parent_key)
            action = "created"
        else:
            key = f"DRYRUN::{path}"
            action = "would_create"
        path_to_key[path] = key
        created_counter[action] += 1
        append_jsonl(
            output_dir / "collection_create_results.jsonl",
            {"action": action, "path": path, "name": part, "key": key, "parent_key": parent_key},
        )
        parent_key = key
    return path_to_key[collection_path]


def reparent_collection(
    *,
    client: zotero.Zotero,
    collection_key_value: str,
    archive_root_key: str,
    apply: bool,
    output_dir: Path,
    counters: Counter[str],
) -> None:
    try:
        collection = client.collection(collection_key_value)
    except ResourceNotFoundError:
        counters["missing"] += 1
        append_jsonl(
            output_dir / "collection_reparent_results.jsonl",
            {"action": "missing", "key": collection_key_value},
        )
        return

    current_parent = collection_parent(collection)
    if current_parent == archive_root_key:
        counters["already_archived"] += 1
        append_jsonl(
            output_dir / "collection_reparent_results.jsonl",
            {"action": "already_archived", "key": collection_key_value, "parent_key": archive_root_key},
        )
        return

    if apply:
        collection["data"]["parentCollection"] = archive_root_key
        response = client.update_collection(collection)
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()
        action = "reparented"
    else:
        action = "would_reparent"

    counters[action] += 1
    append_jsonl(
        output_dir / "collection_reparent_results.jsonl",
        {
            "action": action,
            "key": collection_key_value,
            "old_parent_key": current_parent,
            "new_parent_key": archive_root_key,
        },
    )


def load_archive_root(review_dir: Path) -> str:
    archive_plan = read_json(review_dir / "40_plan_for_confirmation" / "archive_collection_plan.json")
    candidates = [
        row["archive_path"]
        for row in archive_plan
        if row.get("old_path") is None
        and isinstance(row.get("archive_path"), str)
        and str(row["archive_path"]).startswith("90_ARCHIVE/00_PRE_REBUILD_")
    ]
    if not candidates:
        raise RuntimeError("Archive root not found in archive_collection_plan.json")
    return str(candidates[0])


def ensure_rebuild_collections(
    *,
    client: zotero.Zotero,
    review_dir: Path,
    output_dir: Path,
    apply: bool,
) -> tuple[dict[str, str], dict[str, Any]]:
    path_to_key, _ = fetch_collection_state(client)
    counters: Counter[str] = Counter()
    archive_root = load_archive_root(review_dir)

    ensure_collection_path(
        client=client,
        path_to_key=path_to_key,
        collection_path="90_ARCHIVE",
        apply=apply,
        output_dir=output_dir,
        created_counter=counters,
    )
    archive_root_key = ensure_collection_path(
        client=client,
        path_to_key=path_to_key,
        collection_path=archive_root,
        apply=apply,
        output_dir=output_dir,
        created_counter=counters,
    )
    ensure_collection_path(
        client=client,
        path_to_key=path_to_key,
        collection_path=f"{archive_root}/00_UNCOLLECTED",
        apply=apply,
        output_dir=output_dir,
        created_counter=counters,
    )
    ensure_collection_path(
        client=client,
        path_to_key=path_to_key,
        collection_path=f"{archive_root}/00_UNSURE_MANUAL_REVIEW",
        apply=apply,
        output_dir=output_dir,
        created_counter=counters,
    )

    before_collections = read_json(review_dir / "00_export_current_state" / "collection_tree_before.json")
    reparent_counters: Counter[str] = Counter()
    for row in before_collections:
        old_path = str(row["path"])
        if row.get("parent_key") is not None or old_path.startswith("90_ARCHIVE"):
            continue
        reparent_collection(
            client=client,
            collection_key_value=str(row["key"]),
            archive_root_key=archive_root_key,
            apply=apply,
            output_dir=output_dir,
            counters=reparent_counters,
        )

    if apply:
        path_to_key, _ = fetch_collection_state(client)

    target_tree = read_json(review_dir / "30_design_adjustment" / "target_collection_tree.json")
    for row in target_tree:
        ensure_collection_path(
            client=client,
            path_to_key=path_to_key,
            collection_path=str(row["path"]),
            apply=apply,
            output_dir=output_dir,
            created_counter=counters,
        )

    summary = {
        "archive_root": archive_root,
        "created": dict(counters),
        "reparented": dict(reparent_counters),
        "known_collection_paths": len(path_to_key),
    }
    write_json(output_dir / "collection_phase_summary.json", summary)
    return path_to_key, summary


def build_item_additions(review_dir: Path, path_to_key: dict[str, str]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    collection_additions: dict[str, set[str]] = defaultdict(set)
    tag_additions: dict[str, set[str]] = defaultdict(set)

    for row in iter_jsonl(review_dir / "40_plan_for_confirmation" / "archive_item_membership_plan.jsonl"):
        # Old collection membership is preserved by reparenting old collections under archive.
        # Only uncollected items need a synthetic archive collection membership.
        if row.get("from_collection") is None:
            archive_path = str(row["archive_collection"])
            collection_additions[str(row["item_key"])].add(path_to_key[archive_path])

    for row in iter_jsonl(review_dir / "40_plan_for_confirmation" / "item_movement_plan.jsonl"):
        item_key = str(row["item_key"])
        for collection_path in row.get("to_collections", []):
            collection_additions[item_key].add(path_to_key[str(collection_path)])

    for row in iter_jsonl(review_dir / "40_plan_for_confirmation" / "tag_update_plan.jsonl"):
        item_key = str(row["item_key"])
        for tag in row.get("proposed_add_tags", []):
            tag_additions[item_key].add(str(tag))

    return collection_additions, tag_additions


def fetch_items_by_key(client: zotero.Zotero, item_keys: list[str], *, batch_size: int) -> dict[str, dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    for batch in chunks(item_keys, batch_size):
        result = client.items(itemKey=",".join(batch), includeTrashed=1)
        for item in result:
            key = str(item.get("key") or item.get("data", {}).get("key"))
            items[key] = item
    return items


def item_is_deleted(item: dict[str, Any]) -> bool:
    return bool(item.get("data", {}).get("deleted"))


def item_tags(item: dict[str, Any]) -> set[str]:
    return {str(tag.get("tag")) for tag in item.get("data", {}).get("tags", []) if tag.get("tag")}


def item_collections(item: dict[str, Any]) -> set[str]:
    return {str(key) for key in item.get("data", {}).get("collections", []) if key}


def build_plan_rows_by_key(review_dir: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    item_path = review_dir / "00_export_current_state" / "items_before.jsonl"
    if item_path.exists():
        for row in iter_jsonl(item_path):
            key = str(row.get("item_key") or "")
            if key:
                rows.setdefault(key, {}).update(
                    {
                        "item_key": key,
                        "title": row.get("title", ""),
                        "item_type": row.get("item_type", ""),
                        "source_collection_keys": row.get("collections", []),
                        "current_tags": row.get("tags", []),
                    }
                )

    movement_path = review_dir / "40_plan_for_confirmation" / "item_movement_plan.jsonl"
    if movement_path.exists():
        for row in iter_jsonl(movement_path):
            key = str(row.get("item_key") or "")
            if key:
                rows.setdefault(key, {"item_key": key}).update(
                    {
                        "title": row.get("title", rows.get(key, {}).get("title", "")),
                        "from_collections": row.get("from_collections", []),
                        "to_collections": row.get("to_collections", []),
                        "movement_reason": row.get("reason", []),
                        "movement_confidence": row.get("confidence", ""),
                    }
                )

    tag_path = review_dir / "40_plan_for_confirmation" / "tag_update_plan.jsonl"
    if tag_path.exists():
        for row in iter_jsonl(tag_path):
            key = str(row.get("item_key") or "")
            if key:
                rows.setdefault(key, {"item_key": key}).update(
                    {
                        "title": row.get("title", rows.get(key, {}).get("title", "")),
                        "proposed_add_tags": row.get("proposed_add_tags", []),
                        "tag_reason": row.get("reason", []),
                        "tag_confidence": row.get("confidence", ""),
                    }
                )
    return rows


def write_item_progress(
    output_dir: Path,
    *,
    total_items: int,
    total_batches: int,
    batch_index: int,
    processed_items: int,
    counters: Counter[str],
    latest_batch: dict[str, Any],
) -> None:
    write_json(
        output_dir / "item_update_progress.json",
        {
            "total_items": total_items,
            "total_batches": total_batches,
            "batch_index": batch_index,
            "processed_items": processed_items,
            "remaining_items": max(total_items - processed_items, 0),
            "counters": dict(counters),
            "latest_batch": latest_batch,
        },
    )


def apply_item_updates(
    *,
    client: zotero.Zotero,
    review_dir: Path,
    output_dir: Path,
    path_to_key: dict[str, str],
    apply: bool,
    batch_size: int,
) -> dict[str, Any]:
    collection_additions, tag_additions = build_item_additions(review_dir, path_to_key)
    item_keys = sorted(set(collection_additions) | set(tag_additions))
    counters: Counter[str] = Counter()
    missing: list[str] = []
    failed: list[str] = []
    trashed: list[str] = []
    total_items = len(item_keys)
    total_batches = (total_items + batch_size - 1) // batch_size

    if not apply:
        for batch_index, key_batch in enumerate(chunks(item_keys, batch_size), 1):
            for key in key_batch:
                counters["would_update"] += 1
                append_jsonl(
                    output_dir / "item_update_results.jsonl",
                    {
                        "action": "would_update",
                        "item_key": key,
                        "collection_addition_count": len(collection_additions.get(key, set())),
                        "tag_additions": sorted(tag_additions.get(key, set())),
                    },
                )
            processed_items = min(batch_index * batch_size, total_items)
            latest_batch = {
                "action": "dry_run",
                "batch": batch_index,
                "batch_size": len(key_batch),
                "failed": 0,
                "missing": 0,
            }
            write_item_progress(
                output_dir,
                total_items=total_items,
                total_batches=total_batches,
                batch_index=batch_index,
                processed_items=processed_items,
                counters=counters,
                latest_batch=latest_batch,
            )
            print(
                f"[items] dry-run batch {batch_index}/{total_batches} "
                f"processed={processed_items}/{total_items} failed=0 missing=0",
                flush=True,
            )
        summary = {
            "apply": False,
            "planned_item_updates": total_items,
            "planned_collection_memberships": sum(len(value) for value in collection_additions.values()),
            "planned_tag_additions": sum(len(value) for value in tag_additions.values()),
            "result_counts": dict(counters),
            "failed_count": 0,
            "missing_count": 0,
        }
        write_json(output_dir / "item_update_summary.json", summary)
        return summary

    for batch_index, key_batch in enumerate(chunks(item_keys, batch_size), 1):
        batch_started = time.monotonic()
        result_rows: list[dict[str, Any]] = []
        try:
            fetched = fetch_items_by_key(client, key_batch, batch_size=batch_size)
        except Exception as exc:  # noqa: BLE001 - preserve batch failure details for resume/debugging.
            error = short_error(exc)
            failed.extend(key_batch)
            counters["fetch_failed"] += len(key_batch)
            for key in key_batch:
                row = {"action": "failed", "stage": "fetch", "item_key": key, "error": error}
                append_jsonl(output_dir / "item_update_results.jsonl", {"batch": batch_index, **row})
                append_jsonl(output_dir / "failed_results.jsonl", {"batch": batch_index, **row})
            processed_items = min(batch_index * batch_size, total_items)
            latest_batch = {
                "action": "fetch_failed",
                "batch": batch_index,
                "batch_size": len(key_batch),
                "fetched": 0,
                "updated": 0,
                "already_done": 0,
                "failed": len(key_batch),
                "missing": 0,
                "trashed_skipped": 0,
                "elapsed_seconds": round(time.monotonic() - batch_started, 2),
            }
            write_item_progress(
                output_dir,
                total_items=total_items,
                total_batches=total_batches,
                batch_index=batch_index,
                processed_items=processed_items,
                counters=counters,
                latest_batch=latest_batch,
            )
            print(
                f"[items] batch {batch_index}/{total_batches} processed={processed_items}/{total_items} "
                f"fetched=0/{len(key_batch)} updated=0 already_done=0 failed={len(key_batch)} "
                f"missing=0 elapsed={latest_batch['elapsed_seconds']}s",
                flush=True,
            )
            continue

        payloads: list[dict[str, Any]] = []
        payload_rows: dict[str, dict[str, Any]] = {}
        batch_counts: Counter[str] = Counter()
        for key in key_batch:
            item = fetched.get(key)
            if item is None:
                missing.append(key)
                counters["missing"] += 1
                batch_counts["missing"] += 1
                result_rows.append({"action": "missing", "item_key": key})
                continue
            if item_is_deleted(item):
                trashed.append(key)
                counters["trashed_skipped"] += 1
                batch_counts["trashed_skipped"] += 1
                row = {
                    "action": "trashed_skipped",
                    "item_key": key,
                    "reason": "item is in Zotero built-in trash; skipped normal collection/tag writes",
                }
                result_rows.append(row)
                append_jsonl(output_dir / "trashed_skipped_items.jsonl", {"batch": batch_index, **row})
                continue

            existing_collections = item_collections(item)
            existing_tags = item_tags(item)
            new_collection_keys = sorted(collection_additions.get(key, set()) - existing_collections)
            new_tags = sorted(tag_additions.get(key, set()) - existing_tags)
            if not new_collection_keys and not new_tags:
                counters["already_done"] += 1
                batch_counts["already_done"] += 1
                result_rows.append({"action": "already_done", "item_key": key})
                continue

            item["data"]["collections"] = sorted(existing_collections | set(new_collection_keys))
            tag_payload = list(item.get("data", {}).get("tags", []))
            tag_payload.extend({"tag": tag} for tag in new_tags)
            item["data"]["tags"] = tag_payload
            payloads.append(item)
            row = {
                "action": "updated",
                "item_key": key,
                "added_collection_count": len(new_collection_keys),
                "added_collections": new_collection_keys,
                "added_tags": new_tags,
            }
            payload_rows[key] = row

        if payloads:
            try:
                client.update_items(payloads)
                counters["updated"] += len(payloads)
                batch_counts["updated"] += len(payloads)
                result_rows.extend(payload_rows[str(payload.get("key") or payload.get("data", {}).get("key"))] for payload in payloads)
            except Exception as exc:  # noqa: BLE001 - fall back to single-item writes and record failures.
                counters["failed_batches"] += 1
                append_jsonl(
                    output_dir / "failed_batches.jsonl",
                    {
                        "batch": batch_index,
                        "item_keys": [str(payload.get("key") or payload.get("data", {}).get("key")) for payload in payloads],
                        "error": short_error(exc),
                    },
                )
                for payload in payloads:
                    key = str(payload.get("key") or payload.get("data", {}).get("key"))
                    try:
                        client.update_items([payload])
                        counters["updated"] += 1
                        counters["single_retry_updated"] += 1
                        batch_counts["updated"] += 1
                        retry_row = dict(payload_rows[key])
                        retry_row["retry"] = "single_item"
                        result_rows.append(retry_row)
                    except Exception as item_exc:  # noqa: BLE001 - keep going and preserve item failure.
                        failed.append(key)
                        counters["failed"] += 1
                        batch_counts["failed"] += 1
                        failed_row = {
                            "action": "failed",
                            "stage": "update",
                            "item_key": key,
                            "error": short_error(item_exc),
                        }
                        result_rows.append(failed_row)
                        append_jsonl(output_dir / "failed_results.jsonl", {"batch": batch_index, **failed_row})

        for row in result_rows:
            append_jsonl(output_dir / "item_update_results.jsonl", {"batch": batch_index, **row})

        processed_items = min(batch_index * batch_size, total_items)
        latest_batch = {
            "action": "processed",
            "batch": batch_index,
            "batch_size": len(key_batch),
            "fetched": len(fetched),
            "updated": batch_counts["updated"],
            "already_done": batch_counts["already_done"],
            "failed": batch_counts["failed"],
            "missing": batch_counts["missing"],
            "trashed_skipped": batch_counts["trashed_skipped"],
            "elapsed_seconds": round(time.monotonic() - batch_started, 2),
        }
        write_item_progress(
            output_dir,
            total_items=total_items,
            total_batches=total_batches,
            batch_index=batch_index,
            processed_items=processed_items,
            counters=counters,
            latest_batch=latest_batch,
        )
        print(
            f"[items] batch {batch_index}/{total_batches} processed={processed_items}/{total_items} "
            f"fetched={len(fetched)}/{len(key_batch)} updated={batch_counts['updated']} "
            f"already_done={batch_counts['already_done']} failed={batch_counts['failed']} "
            f"missing={batch_counts['missing']} trashed_skipped={batch_counts['trashed_skipped']} "
            f"elapsed={latest_batch['elapsed_seconds']}s",
            flush=True,
        )
        time.sleep(0.2)

    summary = {
        "apply": True,
        "planned_item_updates": total_items,
        "planned_collection_memberships": sum(len(value) for value in collection_additions.values()),
        "planned_tag_additions": sum(len(value) for value in tag_additions.values()),
        "result_counts": dict(counters),
        "failed_count": len(failed),
        "failed_sample": failed[:50],
        "missing_count": len(missing),
        "missing_sample": missing[:50],
        "trashed_skipped_count": len(trashed),
        "trashed_skipped_sample": trashed[:50],
    }
    write_json(output_dir / "item_update_summary.json", summary)
    return summary


def verify_item_updates(
    *,
    client: zotero.Zotero,
    review_dir: Path,
    output_dir: Path,
    path_to_key: dict[str, str],
    batch_size: int,
) -> dict[str, Any]:
    collection_additions, tag_additions = build_item_additions(review_dir, path_to_key)
    item_keys = sorted(set(collection_additions) | set(tag_additions))
    plan_rows = build_plan_rows_by_key(review_dir)
    missing_collection_rows: list[dict[str, Any]] = []
    missing_tag_rows: list[dict[str, Any]] = []
    missing_item_rows: list[dict[str, Any]] = []
    trashed_item_rows: list[dict[str, Any]] = []
    total_items = len(item_keys)
    total_batches = (total_items + batch_size - 1) // batch_size

    for batch_index, key_batch in enumerate(chunks(item_keys, batch_size), 1):
        batch_counts: Counter[str] = Counter()
        fetched = fetch_items_by_key(client, key_batch, batch_size=batch_size)
        for key in key_batch:
            item = fetched.get(key)
            if item is None:
                missing_row = {"item_key": key, **plan_rows.get(key, {})}
                missing_item_rows.append(missing_row)
                append_jsonl(output_dir / "verification_missing_items.jsonl", {"batch": batch_index, **missing_row})
                batch_counts["missing_items"] += 1
                continue
            if item_is_deleted(item):
                trashed_row = {
                    "item_key": key,
                    **plan_rows.get(key, {}),
                    "reason": "item is in Zotero built-in trash; normal collection/tag targets were not verified",
                }
                trashed_item_rows.append(trashed_row)
                append_jsonl(output_dir / "verification_trashed_items.jsonl", {"batch": batch_index, **trashed_row})
                batch_counts["trashed_items"] += 1
                continue
            collections = item_collections(item)
            tags = item_tags(item)
            missing_collections = sorted(collection_additions.get(key, set()) - collections)
            missing_tags = sorted(tag_additions.get(key, set()) - tags)
            if missing_collections:
                missing_collection_rows.append({"item_key": key, "missing_collections": missing_collections})
                batch_counts["missing_collections"] += 1
            if missing_tags:
                missing_tag_rows.append({"item_key": key, "missing_tags": missing_tags})
                batch_counts["missing_tags"] += 1

        processed_items = min(batch_index * batch_size, total_items)
        write_json(
            output_dir / "verification_progress.json",
            {
                "total_items": total_items,
                "total_batches": total_batches,
                "batch_index": batch_index,
                "processed_items": processed_items,
                "remaining_items": max(total_items - processed_items, 0),
                "missing_items": len(missing_item_rows),
                "trashed_items": len(trashed_item_rows),
                "items_with_missing_collections": len(missing_collection_rows),
                "items_with_missing_tags": len(missing_tag_rows),
                "latest_batch": {
                    "batch": batch_index,
                    "batch_size": len(key_batch),
                    "fetched": len(fetched),
                    "missing_items": batch_counts["missing_items"],
                    "trashed_items": batch_counts["trashed_items"],
                    "missing_collections": batch_counts["missing_collections"],
                    "missing_tags": batch_counts["missing_tags"],
                },
            },
        )
        print(
            f"[verify] batch {batch_index}/{total_batches} processed={processed_items}/{total_items} "
            f"fetched={len(fetched)}/{len(key_batch)} missing_items={batch_counts['missing_items']} "
            f"trashed_items={batch_counts['trashed_items']} "
            f"missing_collections={batch_counts['missing_collections']} missing_tags={batch_counts['missing_tags']}",
            flush=True,
        )

    summary = {
        "checked_items": len(item_keys),
        "missing_items": len(missing_item_rows),
        "trashed_items": len(trashed_item_rows),
        "items_with_missing_collections": len(missing_collection_rows),
        "items_with_missing_tags": len(missing_tag_rows),
        "missing_item_sample": missing_item_rows[:50],
        "trashed_item_sample": trashed_item_rows[:50],
        "missing_collection_sample": missing_collection_rows[:50],
        "missing_tag_sample": missing_tag_rows[:50],
    }
    write_json(output_dir / "verification_summary.json", summary)
    for row in missing_collection_rows:
        append_jsonl(output_dir / "verification_missing_collections.jsonl", row)
    for row in missing_tag_rows:
        append_jsonl(output_dir / "verification_missing_tags.jsonl", row)
    return summary


def write_verification_markdown(path: Path, *, collection_summary: dict[str, Any], item_summary: dict[str, Any], verify: dict[str, Any]) -> None:
    lines = ["# Zotero Library Rebuild Verification", ""]
    if collection_summary:
        lines.extend(
            [
                "## Collection Phase",
                "",
                f"- archive root: `{collection_summary.get('archive_root')}`",
                f"- created counters: `{collection_summary.get('created')}`",
                f"- reparent counters: `{collection_summary.get('reparented')}`",
                "",
            ]
        )
    if item_summary:
        lines.extend(
            [
                "## Item And Tag Phase",
                "",
                f"- planned item updates: {item_summary.get('planned_item_updates')}",
                f"- planned collection memberships: {item_summary.get('planned_collection_memberships')}",
                f"- planned tag additions: {item_summary.get('planned_tag_additions')}",
                f"- result counts: `{item_summary.get('result_counts', {})}`",
                f"- failed during apply: {item_summary.get('failed_count', 0)}",
                f"- missing during apply: {item_summary.get('missing_count', 0)}",
                f"- trashed skipped during apply: {item_summary.get('trashed_skipped_count', 0)}",
                "",
            ]
        )
    if verify:
        lines.extend(
            [
                "## Post-Write Verification",
                "",
                f"- checked items: {verify.get('checked_items')}",
                f"- missing items: {verify.get('missing_items')}",
                f"- trashed items skipped: {verify.get('trashed_items', 0)}",
                f"- items with missing collections: {verify.get('items_with_missing_collections')}",
                f"- items with missing tags: {verify.get('items_with_missing_tags')}",
                "",
            ]
        )
    if not collection_summary and not item_summary and not verify:
        lines.extend(["No phase data was produced.", ""])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply a reviewed Zotero library rebuild plan via Zotero Web API.")
    parser.add_argument("--review-dir", default="current-state-review", help="Review directory under log/zotero-library-rebuild.")
    parser.add_argument("--output-dir", default="", help="Execution output directory. Defaults under review_dir/50_execution_results.")
    parser.add_argument("--profile", default=None, help="Config profile.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Web API item update batch size.")
    parser.add_argument("--apply", action="store_true", help="Actually write to Zotero. Omit for dry-run.")
    parser.add_argument(
        "--phase",
        choices=["all", "collections", "items", "verify"],
        default="all",
        help="Apply only one phase.",
    )
    args = parser.parse_args()

    if args.batch_size < 1 or args.batch_size > 50:
        raise SystemExit("--batch-size must be between 1 and 50")

    review_dir = resolve_review_dir(args.review_dir)
    if not (review_dir / "plan.md").exists():
        raise SystemExit(f"Reviewed plan not found: {review_dir / 'plan.md'}")
    output_dir = Path(args.output_dir).resolve() if args.output_dir else default_output_dir(review_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        output_dir / "apply_request.json",
        {
            "review_dir": str(review_dir),
            "output_dir": str(output_dir),
            "apply": args.apply,
            "phase": args.phase,
            "batch_size": args.batch_size,
        },
    )

    client = build_client(args.profile)
    print(f"[preflight] review_dir={review_dir}", flush=True)
    print(f"[preflight] output_dir={output_dir}", flush=True)
    print(f"[preflight] apply={args.apply} phase={args.phase}", flush=True)

    collection_summary: dict[str, Any] = {}
    item_summary: dict[str, Any] = {}
    verify_summary: dict[str, Any] = {}

    if args.phase in {"all", "collections"}:
        path_to_key, collection_summary = ensure_rebuild_collections(
            client=client,
            review_dir=review_dir,
            output_dir=output_dir,
            apply=args.apply,
        )
    else:
        path_to_key, _ = fetch_collection_state(client)

    if args.phase in {"all", "items"}:
        item_summary = apply_item_updates(
            client=client,
            review_dir=review_dir,
            output_dir=output_dir,
            path_to_key=path_to_key,
            apply=args.apply,
            batch_size=args.batch_size,
        )

    if args.phase in {"all", "verify"} and args.apply:
        path_to_key, _ = fetch_collection_state(client)
        verify_summary = verify_item_updates(
            client=client,
            review_dir=review_dir,
            output_dir=output_dir,
            path_to_key=path_to_key,
            batch_size=args.batch_size,
        )
        write_json(output_dir / "collection_tree_after_api.json", client.all_collections())

    write_json(
        output_dir / "apply_summary.json",
        {
            "collection_summary": collection_summary,
            "item_summary": item_summary,
            "verification_summary": verify_summary,
        },
    )
    write_verification_markdown(
        output_dir / "verification_summary.md",
        collection_summary=collection_summary,
        item_summary=item_summary,
        verify=verify_summary,
    )
    print(json.dumps({"ok": True, "output_dir": str(output_dir), "apply": args.apply}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PyZoteroError, httpx.HTTPError) as exc:
        raise SystemExit(f"Zotero API error: {exc}") from exc

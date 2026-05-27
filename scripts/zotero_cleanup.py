from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any

from pyzotero import zotero

from zotero_cli_agents.config import get_data_dir, load_config, resolve_write_credentials

EXCLUDED_ITEM_TYPES = ("attachment", "note", "annotation")
FIELD_NAMES = ("title", "abstractNote", "publicationTitle", "journalAbbreviation", "DOI", "url", "date")
CSV_FIELDS = (
    "key",
    "decision",
    "reason",
    "high_hits",
    "medium_hits",
    "guard_hits",
    "title",
    "first_creator",
    "publicationTitle",
    "journalAbbreviation",
    "date",
    "doi",
    "url",
    "collections",
    "collection_keys",
    "tags",
    "dateAdded",
    "dateModified",
)


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def clean_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return (
        text.replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("\u00a0", " ")
        .replace("\r", " ")
        .replace("\n", " ")
    )


SHORT_TOKEN_RE = re.compile(r"^[a-z0-9+-]{1,4}$")


def term_matches(text: str, term: str) -> bool:
    term = term.lower()
    if SHORT_TOKEN_RE.fullmatch(term):
        return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None
    return term in text


def chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def load_rules(path: Path) -> dict[str, Any]:
    rules = json.loads(path.read_text(encoding="utf-8"))
    if "zotero_scope" not in rules:
        raise ValueError(f"Rules file missing zotero_scope: {path}")
    target = rules["zotero_scope"].get("target_trash_collection") or {}
    if not target.get("key") or not target.get("name"):
        raise ValueError("Rules file must define zotero_scope.target_trash_collection.name/key")
    return rules


def fetch_library_rows(db_path: Path, local_library_id: int = 1) -> dict[int, dict[str, Any]]:
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row

    fields = {r["fieldName"]: r["fieldID"] for r in conn.execute("SELECT fieldID, fieldName FROM fields")}
    item_types = {r["itemTypeID"]: r["typeName"] for r in conn.execute("SELECT itemTypeID, typeName FROM itemTypes")}
    field_ids = [fields[name] for name in FIELD_NAMES if name in fields]
    field_placeholders = ",".join("?" * len(field_ids))
    excluded_placeholders = ",".join("?" * len(EXCLUDED_ITEM_TYPES))

    base_rows = conn.execute(
        f"""
        SELECT i.itemID, i.key, i.itemTypeID, i.dateAdded, i.dateModified,
               CASE WHEN d.itemID IS NULL THEN 0 ELSE 1 END AS deleted
        FROM items i
        LEFT JOIN deletedItems d ON d.itemID = i.itemID
        WHERE i.libraryID = ?
          AND i.itemTypeID NOT IN (
            SELECT itemTypeID FROM itemTypes WHERE typeName IN ({excluded_placeholders})
          )
        """,
        (local_library_id, *EXCLUDED_ITEM_TYPES),
    ).fetchall()

    items: dict[int, dict[str, Any]] = {}
    for row in base_rows:
        items[row["itemID"]] = {
            "itemID": row["itemID"],
            "key": row["key"],
            "item_type": item_types.get(row["itemTypeID"], "unknown"),
            "dateAdded": row["dateAdded"],
            "dateModified": row["dateModified"],
            "deleted": bool(row["deleted"]),
        }

    item_ids = list(items)
    for start in range(0, len(item_ids), 900):
        batch = item_ids[start : start + 900]
        placeholders = ",".join("?" * len(batch))

        if field_ids:
            rows = conn.execute(
                f"""
                SELECT id.itemID, f.fieldName, iv.value
                FROM itemData id
                JOIN fields f ON id.fieldID = f.fieldID
                JOIN itemDataValues iv ON id.valueID = iv.valueID
                WHERE id.itemID IN ({placeholders}) AND id.fieldID IN ({field_placeholders})
                """,
                (*batch, *field_ids),
            ).fetchall()
            for row in rows:
                items[row["itemID"]][row["fieldName"]] = row["value"] or ""

        tag_rows = conn.execute(
            f"""
            SELECT it.itemID, t.name
            FROM itemTags it
            JOIN tags t ON it.tagID = t.tagID
            WHERE it.itemID IN ({placeholders})
            """,
            batch,
        ).fetchall()
        for row in tag_rows:
            items[row["itemID"]].setdefault("tags", []).append(row["name"])

        collection_rows = conn.execute(
            f"""
            SELECT ci.itemID, c.key, c.collectionName
            FROM collectionItems ci
            JOIN collections c ON ci.collectionID = c.collectionID
            WHERE ci.itemID IN ({placeholders})
            """,
            batch,
        ).fetchall()
        for row in collection_rows:
            items[row["itemID"]].setdefault("collection_keys", []).append(row["key"])
            items[row["itemID"]].setdefault("collections", []).append(row["collectionName"])

        creator_rows = conn.execute(
            f"""
            SELECT ic.itemID, c.firstName, c.lastName
            FROM itemCreators ic
            JOIN creators c ON ic.creatorID = c.creatorID
            WHERE ic.itemID IN ({placeholders}) AND ic.orderIndex = 0
            """,
            batch,
        ).fetchall()
        for row in creator_rows:
            items[row["itemID"]]["first_creator"] = " ".join(
                part for part in (row["firstName"], row["lastName"]) if part
            )

    conn.close()
    return items


def classify_item(row: dict[str, Any], rules: dict[str, Any]) -> tuple[str, str, list[str], list[str], list[str]]:
    high_terms = [str(term).lower() for term in rules.get("high_precision_keep_terms", [])]
    medium_terms = [str(term).lower() for term in rules.get("medium_precision_keep_terms", [])]
    guard_terms = [str(term).lower() for term in rules.get("reject_guard_terms", [])]

    text_parts: list[Any] = [
        row.get("title"),
        row.get("abstractNote"),
        row.get("publicationTitle"),
        row.get("journalAbbreviation"),
        *(row.get("tags", []) or []),
        *(row.get("collections", []) or []),
    ]
    text = clean_text(" ".join(str(part or "") for part in text_parts)).lower()

    high_hits = sorted({term for term in high_terms if term_matches(text, term)})
    medium_hits = sorted({term for term in medium_terms if term_matches(text, term)})
    guard_hits = sorted({term for term in guard_terms if term_matches(text, term)})

    if high_hits:
        return "keep", "high_precision_match", high_hits, medium_hits, guard_hits
    if len(medium_hits) >= 2:
        return "keep", "multiple_medium_precision_matches", high_hits, medium_hits, guard_hits
    if len(medium_hits) == 1:
        return "unsure", "single_medium_precision_match", high_hits, medium_hits, guard_hits
    if guard_hits:
        return "unsure", "reject_guard_match", high_hits, medium_hits, guard_hits
    return "reject", "no_rule_match", high_hits, medium_hits, guard_hits


def build_classification_outputs(
    *,
    rules: dict[str, Any],
    rules_path: Path,
    db_path: Path,
    output_dir: Path,
    progress_path: Path,
) -> tuple[list[str], dict[str, Any]]:
    classify_types = set(rules["zotero_scope"].get("classify_item_types") or ["journalArticle"])
    items = fetch_library_rows(db_path)

    counts_by_type_all = Counter(row["item_type"] for row in items.values())
    counts_by_type_active = Counter(row["item_type"] for row in items.values() if not row["deleted"])
    rows: list[dict[str, Any]] = []

    for row in items.values():
        if row["item_type"] not in classify_types or row["deleted"]:
            continue
        decision, reason, high_hits, medium_hits, guard_hits = classify_item(row, rules)
        rows.append(
            {
                "key": row.get("key", ""),
                "decision": decision,
                "reason": reason,
                "high_hits": "; ".join(high_hits),
                "medium_hits": "; ".join(medium_hits),
                "guard_hits": "; ".join(guard_hits),
                "title": clean_text(row.get("title", "")).strip(),
                "first_creator": row.get("first_creator", ""),
                "publicationTitle": row.get("publicationTitle", ""),
                "journalAbbreviation": row.get("journalAbbreviation", ""),
                "date": row.get("date", ""),
                "doi": row.get("DOI", ""),
                "url": row.get("url", ""),
                "collections": "; ".join(row.get("collections", [])),
                "collection_keys": "; ".join(row.get("collection_keys", [])),
                "tags": "; ".join(row.get("tags", [])),
                "dateAdded": row.get("dateAdded", ""),
                "dateModified": row.get("dateModified", ""),
            }
        )

    rows.sort(key=lambda r: (r["decision"], r["publicationTitle"].lower(), r["title"].lower(), r["key"]))
    keep_rows = [row for row in rows if row["decision"] == "keep"]
    unsure_rows = [row for row in rows if row["decision"] == "unsure"]
    reject_rows = [row for row in rows if row["decision"] == "reject"]
    by_label = Counter(row["decision"] for row in rows)
    by_reason = Counter(row["reason"] for row in rows)

    write_csv(output_dir / "classification-all.csv", rows)
    write_csv(output_dir / "keep.csv", keep_rows)
    write_csv(output_dir / "unsure.csv", unsure_rows)
    write_csv(output_dir / "reject-candidates.csv", reject_rows)

    target = rules["zotero_scope"]["target_trash_collection"]
    plan = {
        "status": "generated",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rules_file": str(rules_path),
        "target_collection": target,
        "operation_if_confirmed": "set reject candidate journalArticle item collections to only the target collection",
        "reject_count": len(reject_rows),
        "reject_item_keys": [row["key"] for row in reject_rows],
    }
    write_json(output_dir / "cleanup-plan.json", plan)

    summary = {
        "status": "generated",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rules_file": str(rules_path),
        "local_database": str(db_path),
        "classification_scope": {
            "classify_item_types": sorted(classify_types),
            "all_main_items_by_type": dict(counts_by_type_all.most_common()),
            "active_main_items_by_type": dict(counts_by_type_active.most_common()),
            "already_zotero_deleted_main_items": sum(1 for row in items.values() if row["deleted"]),
            "active_journal_articles_classified": len(rows),
            "non_journal_active_items_preserved": sum(
                1 for row in items.values() if not row["deleted"] and row["item_type"] not in classify_types
            ),
        },
        "classification_counts": dict(by_label),
        "reason_counts": dict(by_reason),
        "target_collection": target,
        "output_files": {
            "classification_all_csv": str(output_dir / "classification-all.csv"),
            "keep_csv": str(output_dir / "keep.csv"),
            "unsure_csv": str(output_dir / "unsure.csv"),
            "reject_candidates_csv": str(output_dir / "reject-candidates.csv"),
            "cleanup_plan_json": str(output_dir / "cleanup-plan.json"),
        },
        "sample_unsure": unsure_rows[:30],
        "sample_reject": reject_rows[:30],
    }
    write_json(output_dir / "classification-summary.json", summary)

    md_lines = [
        "# Zotero Cleanup Classification Preview",
        "",
        "Status: generated. No Zotero item is deleted by this workflow.",
        "",
        f"Active journalArticle items classified: {len(rows)}",
        f"Keep: {by_label.get('keep', 0)}",
        f"Unsure: {by_label.get('unsure', 0)}",
        f"Move candidates for {target['name']}: {by_label.get('reject', 0)}",
        f"Already in Zotero trash and excluded: {summary['classification_scope']['already_zotero_deleted_main_items']}",
        f"Non-journal active items preserved: {summary['classification_scope']['non_journal_active_items_preserved']}",
        "",
        "Output files:",
    ]
    for label, path in summary["output_files"].items():
        md_lines.append(f"- {label}: `{path}`")
    md_lines.extend(["", "Unsure sample:", ""])
    for row in unsure_rows[:20]:
        hits = row["medium_hits"] or row["guard_hits"] or row["high_hits"]
        md_lines.append(f"- {row['key']} | {row['publicationTitle']} | {row['title']} | {row['reason']} | {hits}")
    md_lines.extend(["", "Move-candidate sample:", ""])
    for row in reject_rows[:20]:
        md_lines.append(f"- {row['key']} | {row['publicationTitle']} | {row['title']}")
    (output_dir / "classification-preview.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    append_jsonl(
        progress_path,
        {
            "event": "classified",
            "active_journal_articles": len(rows),
            "counts": dict(by_label),
            "reason_counts": dict(by_reason),
        },
    )
    return [row["key"] for row in reject_rows], summary


def read_key_file(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def append_key(path: Path, key: str) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(key + "\n")


def fetch_web_items(zot: zotero.Zotero, keys: list[str]) -> dict[str, dict[str, Any]]:
    if not keys:
        return {}
    items = zot.items(itemKey=",".join(keys), format="json", include="data", limit=len(keys))
    fetched: dict[str, dict[str, Any]] = {}
    for item in items:
        data = item.get("data", item)
        key = data.get("key")
        if key:
            fetched[str(key)] = data
    return fetched


def update_items_batch(zot: zotero.Zotero, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    zot.update_items(items)


def apply_cleanup(
    *,
    keys: list[str],
    rules: dict[str, Any],
    output_dir: Path,
    batch_size: int,
    resume: bool,
    profile: str | None,
    progress_path: Path,
) -> dict[str, Any]:
    cfg = load_config(profile=profile)
    library_id, api_key = resolve_write_credentials(cfg, library_type="user", group_id=None)
    if not library_id or not api_key:
        raise RuntimeError("Zotero Web API credentials are not configured.")

    target = rules["zotero_scope"]["target_trash_collection"]
    target_key = str(target["key"])
    target_name = str(target["name"])

    zot = zotero.Zotero(library_id, "user", api_key)
    target_payload = zot.collection(target_key, format="json")
    target_data = target_payload.get("data", target_payload) if isinstance(target_payload, dict) else {}
    if target_data.get("name") and target_data["name"] != target_name:
        raise RuntimeError(f"Target collection key {target_key} is named {target_data['name']!r}, not {target_name!r}.")

    completed_path = output_dir / "completed-keys.txt"
    failed_path = output_dir / "failed-keys.txt"
    api_results_path = output_dir / "api-results.ndjson"
    completed = read_key_file(completed_path) if resume else set()

    pending = [key for key in keys if key not in completed]
    batches = chunked(pending, batch_size)
    started = time.monotonic()
    totals = Counter({"planned": len(keys), "pending": len(pending), "completed_before": len(completed)})

    log(f"[apply] target={target_name} ({target_key}) planned={len(keys)} pending={len(pending)} batch_size={batch_size}")
    append_jsonl(progress_path, {"event": "apply_start", "target": target, "planned": len(keys), "pending": len(pending)})

    for batch_index, batch_keys in enumerate(batches, start=1):
        batch_started = time.monotonic()
        fetched = fetch_web_items(zot, batch_keys)
        updates: list[dict[str, Any]] = []
        already_target: list[str] = []
        missing: list[str] = []

        for key in batch_keys:
            data = fetched.get(key)
            if data is None:
                missing.append(key)
                continue
            current = list(data.get("collections") or [])
            if current == [target_key]:
                already_target.append(key)
                continue
            data["collections"] = [target_key]
            updates.append(data)

        batch_failed: list[dict[str, str]] = []
        moved_keys: list[str] = []
        if updates:
            try:
                update_items_batch(zot, updates)
                moved_keys = [str(item["key"]) for item in updates]
            except Exception:
                # Fallback to one-by-one updates to isolate failures.
                for item in updates:
                    key = str(item["key"])
                    try:
                        response = zot.update_item(item)
                        if hasattr(response, "raise_for_status"):
                            response.raise_for_status()
                        moved_keys.append(key)
                    except Exception as item_exc:  # pragma: no cover - exercised against live API
                        batch_failed.append({"key": key, "error": str(item_exc)})

        for key in moved_keys + already_target:
            if key not in completed:
                append_key(completed_path, key)
                completed.add(key)

        for key in missing:
            append_key(failed_path, key)
            batch_failed.append({"key": key, "error": "missing_from_web_api"})

        for failure in batch_failed:
            append_jsonl(api_results_path, {"event": "failed", **failure})

        totals.update(
            {
                "fetched": len(fetched),
                "moved": len(moved_keys),
                "already_target": len(already_target),
                "missing": len(missing),
                "failed": len(batch_failed),
            }
        )
        elapsed = time.monotonic() - started
        batch_elapsed = time.monotonic() - batch_started
        completed_now = len(completed)
        percent = (completed_now * 100.0 / len(keys)) if keys else 100.0
        progress = {
            "event": "batch_complete",
            "batch": batch_index,
            "batch_total": len(batches),
            "batch_size": len(batch_keys),
            "fetched": len(fetched),
            "moved": len(moved_keys),
            "already_target": len(already_target),
            "missing": len(missing),
            "failed": len(batch_failed),
            "completed": completed_now,
            "planned": len(keys),
            "percent": round(percent, 2),
            "elapsed_seconds": round(elapsed, 1),
            "batch_elapsed_seconds": round(batch_elapsed, 1),
        }
        append_jsonl(progress_path, progress)
        append_jsonl(api_results_path, progress)
        log(
            f"[batch {batch_index}/{len(batches)}] fetched={len(fetched)} moved={len(moved_keys)} "
            f"already={len(already_target)} failed={len(batch_failed)} completed={completed_now}/{len(keys)} "
            f"({percent:.1f}%) elapsed={elapsed:.1f}s"
        )

    summary = {
        "planned": len(keys),
        "completed": len(completed),
        "failed": totals["failed"],
        "missing": totals["missing"],
        "moved": totals["moved"],
        "already_target": totals["already_target"],
        "elapsed_seconds": round(time.monotonic() - started, 1),
    }
    write_json(output_dir / "apply-summary.json", summary)
    append_jsonl(progress_path, {"event": "apply_complete", **summary})
    return summary


def postcheck(
    *,
    keys: list[str],
    rules: dict[str, Any],
    output_dir: Path,
    batch_size: int,
    profile: str | None,
    progress_path: Path,
) -> dict[str, Any]:
    cfg = load_config(profile=profile)
    library_id, api_key = resolve_write_credentials(cfg, library_type="user", group_id=None)
    zot = zotero.Zotero(library_id, "user", api_key)
    target_key = str(rules["zotero_scope"]["target_trash_collection"]["key"])

    only_target: list[str] = []
    not_only_target: list[dict[str, Any]] = []
    missing: list[str] = []

    for batch_keys in chunked(keys, batch_size):
        fetched = fetch_web_items(zot, batch_keys)
        for key in batch_keys:
            data = fetched.get(key)
            if data is None:
                missing.append(key)
                continue
            collections = list(data.get("collections") or [])
            if collections == [target_key]:
                only_target.append(key)
            else:
                not_only_target.append({"key": key, "collections": collections})

    result = {
        "checked": len(keys),
        "target_key": target_key,
        "only_target_count": len(only_target),
        "not_only_target_count": len(not_only_target),
        "missing_count": len(missing),
        "not_only_target_sample": not_only_target[:50],
        "missing_sample": missing[:50],
    }
    write_json(output_dir / "postcheck-web-api.json", result)
    append_jsonl(progress_path, {"event": "postcheck", **result})
    log(
        f"[postcheck] checked={result['checked']} only_target={result['only_target_count']} "
        f"not_only_target={result['not_only_target_count']} missing={result['missing_count']}"
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify Zotero journal articles and move unrelated items to a collection.")
    parser.add_argument("--rules", type=Path, required=True, help="Rules JSON file.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Run output directory under log/.")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--apply", action="store_true", help="Apply Web API collection moves.")
    parser.add_argument("--resume", action="store_true", help="Skip keys already listed in completed-keys.txt.")
    parser.add_argument("--profile", default="", help="Optional config profile.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.batch_size < 1 or args.batch_size > 50:
        raise ValueError("--batch-size must be between 1 and 50")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "progress.ndjson"

    rules_path = args.rules.resolve()
    rules = load_rules(rules_path)
    write_json(output_dir / "rules-used.json", rules)

    cfg = load_config(profile=args.profile or None)
    db_path = get_data_dir(cfg) / "zotero.sqlite"
    if not db_path.exists():
        raise FileNotFoundError(f"Zotero database not found: {db_path}")

    log(f"[preflight] rules={rules_path}")
    log(f"[preflight] output_dir={output_dir}")
    log(f"[preflight] local_db={db_path}")

    keys, summary = build_classification_outputs(
        rules=rules,
        rules_path=rules_path,
        db_path=db_path,
        output_dir=output_dir,
        progress_path=progress_path,
    )
    counts = summary["classification_counts"]
    log(
        f"[preflight] active journalArticle={summary['classification_scope']['active_journal_articles_classified']} "
        f"keep={counts.get('keep', 0)} unsure={counts.get('unsure', 0)} move_candidates={counts.get('reject', 0)}"
    )

    if not args.apply:
        log("[dry-run] no Zotero Web API writes were performed. Re-run with -Apply to move candidates.")
        return 0

    apply_summary = apply_cleanup(
        keys=keys,
        rules=rules,
        output_dir=output_dir,
        batch_size=args.batch_size,
        resume=args.resume,
        profile=args.profile or None,
        progress_path=progress_path,
    )
    if apply_summary["failed"] or apply_summary["missing"]:
        log("[apply] completed with failures; inspect failed-keys.txt and api-results.ndjson.")
    postcheck(
        keys=keys,
        rules=rules,
        output_dir=output_dir,
        batch_size=args.batch_size,
        profile=args.profile or None,
        progress_path=progress_path,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        log(f"[error] {exc}")
        raise

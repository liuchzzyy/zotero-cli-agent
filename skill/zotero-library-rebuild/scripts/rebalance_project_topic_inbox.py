from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from pyzotero import zotero
from pyzotero.zotero_errors import PyZoteroError

from zotero_cli_agents.config import load_config, project_root, resolve_write_credentials

API_TIMEOUT = 300.0
PROJECT_PATH = "20_PROJECTS/00_PROJECT_INBOX"
TOPIC_PATH = "30_TOPICS/00_TOPIC_INBOX"
PARENT_EXCLUDED_TYPES = {"attachment", "note", "annotation"}

TECH_REGEX = [
    r"\bxas\b",
    r"\bxafs\b",
    r"\bexafs\b",
    r"\bxanes\b",
    r"\bxes\b",
    r"\beels\b",
    r"\bxps\b",
    r"\bxrd\b",
    r"\braman\b",
    r"\bftir\b",
    r"\btxm\b",
    r"\btem\b",
    r"\bstxm\b",
    r"\bstem\b",
    r"\bfeff\b",
    r"\bfeffit\b",
    r"\bhaadf\b",
    r"\bnmr\b",
    r"\bepr\b",
    r"\btof sims\b",
    r"\btof-sims\b",
    r"\buv vis\b",
    r"\buv-vis\b",
    r"\bmossbauer\b",
    r"\bmuon\b",
    r"\bμ\+sr\b",
    r"\bwavelet\b",
    r"\bptychography\b",
    r"\btomography\b",
    r"\bspectromicroscopy\b",
    r"\bspectroscopy\b",
    r"\bmicroscopy\b",
    r"\bdiffraction\b",
    r"\bscattering\b",
    r"\bsynchrotron\b",
    r"\bbeamline\b",
    r"\bmantis\b",
    r"\batomap\b",
    r"\bqexafs\b",
    r"\bedxas\b",
    r"\bherfd\b",
    r"\brixs\b",
    r"\bx ray absorption\b",
    r"\bx-ray absorption\b",
    r"\bx ray emission\b",
    r"\bx-ray emission\b",
    r"\bx ray fluorescence\b",
    r"\bx-ray fluorescence\b",
]

TECH_CN = [
    "同步辐射",
    "光谱",
    "谱学",
    "显微",
    "衍射",
    "断层扫描",
    "小波",
    "归一化",
    "前边",
    "预边",
    "穆斯堡尔",
    "吸收谱",
    "发射谱",
    "荧光显微",
]


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temp_path.replace(path)


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_client(profile: str | None) -> zotero.Zotero:
    cfg = load_config(profile=profile)
    library_id, api_key = resolve_write_credentials(cfg, library_type="user")
    client = zotero.Zotero(str(library_id), "user", api_key)
    if client.client is not None:
        client.client.timeout = httpx.Timeout(API_TIMEOUT)
    return client


def collection_key(collection: dict[str, Any]) -> str:
    return str(collection.get("key") or collection.get("data", {}).get("key") or "")


def collection_name(collection: dict[str, Any]) -> str:
    return str(collection.get("data", {}).get("name") or collection.get("name") or "")


def collection_parent(collection: dict[str, Any]) -> str | None:
    parent = collection.get("data", {}).get("parentCollection")
    return str(parent) if parent else None


def fetch_collection_state(client: zotero.Zotero) -> dict[str, str]:
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

    return {path_for(key): key for key in by_key}


def normalize_text(text: str) -> str:
    return re.sub(r"[-_/]", " ", (text or "").lower())


def has_tech(text: str) -> bool:
    normalized = normalize_text(text)
    if any(re.search(pattern, normalized) for pattern in TECH_REGEX):
        return True
    return any(keyword in normalized for keyword in TECH_CN)


def is_method_centric(item: dict[str, Any]) -> bool:
    data = item.get("data", {})
    title = str(data.get("title") or "")
    citation_key = str(data.get("citationKey") or "")
    first_slot = citation_key.split("|", 1)[0].strip() if citation_key else ""
    return has_tech(title) or has_tech(first_slot)


def item_type(item: dict[str, Any]) -> str:
    return str(item.get("data", {}).get("itemType") or "")


def item_key(item: dict[str, Any]) -> str:
    return str(item.get("key") or item.get("data", {}).get("key") or "")


def item_title(item: dict[str, Any]) -> str:
    return str(item.get("data", {}).get("title") or "")


def item_citation_key(item: dict[str, Any]) -> str:
    return str(item.get("data", {}).get("citationKey") or "")


def is_parent_item(item: dict[str, Any]) -> bool:
    return item_type(item) not in PARENT_EXCLUDED_TYPES


def fetch_collection_items(client: zotero.Zotero, collection_id: str) -> dict[str, dict[str, Any]]:
    result = client.everything(client.collection_items(collection_id))
    items = [item for item in result if is_parent_item(item)]
    return {item_key(item): item for item in items if item_key(item)}


def fetch_items_by_keys(client: zotero.Zotero, keys: list[str], batch_size: int = 50) -> dict[str, dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    for index in range(0, len(keys), batch_size):
        batch = keys[index : index + batch_size]
        result = client.items(itemKey=",".join(batch), includeTrashed=1)
        for item in result:
            if is_parent_item(item) and item_key(item):
                items[item_key(item)] = item
    return items


def resolve_output_dir(raw_output_dir: str) -> Path:
    root = project_root()
    log_root = (root / "log").resolve()
    run_root = log_root / "zotero-library-rebuild"
    if raw_output_dir:
        candidate = Path(raw_output_dir)
        if candidate.is_absolute():
            output_dir = candidate.resolve()
        elif candidate.parts and candidate.parts[0].lower() == "log":
            output_dir = (root / candidate).resolve()
        else:
            output_dir = (run_root / candidate).resolve()
    else:
        output_dir = (run_root / f"rebalance-project-topic-{now_stamp()}").resolve()
    if output_dir == log_root or log_root not in output_dir.parents:
        raise SystemExit(f"Output directory must be under repository log directory: {log_root}")
    return output_dir


def build_topic_to_project_ops(
    *,
    approved_rows: list[dict[str, Any]],
    items_by_key: dict[str, dict[str, Any]],
    project_key: str,
    topic_key: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    operations: list[dict[str, Any]] = []
    missing_keys: list[str] = []
    for row in approved_rows:
        key = str(row["key"])
        item = items_by_key.get(key)
        if item is None:
            missing_keys.append(key)
            continue
        current_collections = set(item.get("data", {}).get("collections", []))
        desired_collections = sorted((current_collections - {topic_key}) | {project_key})
        if desired_collections == sorted(current_collections):
            continue
        operations.append(
            {
                "operation": "topic_to_project",
                "key": key,
                "title": item_title(item),
                "zh_title": row.get("zh_title", ""),
                "keywords": row.get("keywords", ""),
                "group": row.get("group", ""),
                "reason": row.get("reason", ""),
                "from_collections": sorted(current_collections),
                "to_collections": desired_collections,
            }
        )
    return operations, missing_keys


def build_project_to_topic_ops(
    *,
    project_items: dict[str, dict[str, Any]],
    approved_keys: set[str],
    project_key: str,
    topic_key: str,
) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for key, item in sorted(project_items.items(), key=lambda pair: item_title(pair[1]).lower()):
        if key in approved_keys:
            continue
        if not is_method_centric(item):
            continue
        current_collections = set(item.get("data", {}).get("collections", []))
        desired_collections = sorted((current_collections - {project_key}) | {topic_key})
        if desired_collections == sorted(current_collections):
            continue
        citation_key = item_citation_key(item)
        operations.append(
            {
                "operation": "project_to_topic",
                "key": key,
                "title": item_title(item),
                "zh_title": "",
                "keywords": citation_key.split("|", 1)[0].strip() if citation_key else "",
                "group": "method_centric_project_item",
                "reason": "标题或 citationKey 第一槽明确是高端表征/表征技术细节本体，按当前规则应归入 00_TOPIC_INBOX。",
                "from_collections": sorted(current_collections),
                "to_collections": desired_collections,
            }
        )
    return operations


def apply_operations(
    *,
    client: zotero.Zotero,
    operations: list[dict[str, Any]],
    items_by_key: dict[str, dict[str, Any]],
    apply: bool,
    output_dir: Path,
    batch_size: int,
) -> dict[str, Any]:
    counters: Counter[str] = Counter()
    results: list[dict[str, Any]] = []
    if not apply:
        for op in operations:
            counters["would_update"] += 1
            results.append({"action": "would_update", **op})
        write_jsonl(output_dir / "apply_results.jsonl", results)
        return {"apply": False, "result_counts": dict(counters)}

    for index in range(0, len(operations), batch_size):
        batch_ops = operations[index : index + batch_size]
        payloads: list[dict[str, Any]] = []
        for op in batch_ops:
            item = items_by_key[op["key"]]
            item["data"]["collections"] = op["to_collections"]
            payloads.append(item)
        client.update_items(payloads)
        counters["updated"] += len(batch_ops)
        for op in batch_ops:
            results.append({"action": "updated", **op})
        print(
            f"[apply] batch {(index // batch_size) + 1}/{((len(operations) + batch_size - 1) // batch_size)} "
            f"processed={min(index + batch_size, len(operations))}/{len(operations)}",
            flush=True,
        )
        time.sleep(0.2)
    write_jsonl(output_dir / "apply_results.jsonl", results)
    return {"apply": True, "result_counts": dict(counters)}


def verify_operations(
    *,
    client: zotero.Zotero,
    operations: list[dict[str, Any]],
    batch_size: int,
    output_dir: Path,
) -> dict[str, Any]:
    keys = [op["key"] for op in operations]
    fetched = fetch_items_by_keys(client, keys, batch_size=batch_size)
    missing_keys: list[str] = []
    bad_rows: list[dict[str, Any]] = []
    ok_count = 0
    for op in operations:
        item = fetched.get(op["key"])
        if item is None:
            missing_keys.append(op["key"])
            continue
        actual = sorted(item.get("data", {}).get("collections", []))
        if actual != op["to_collections"]:
            bad_rows.append(
                {
                    "key": op["key"],
                    "title": op["title"],
                    "expected_collections": op["to_collections"],
                    "actual_collections": actual,
                }
            )
        else:
            ok_count += 1
    write_json(output_dir / "verify_summary.json", {"ok_count": ok_count, "missing_keys": missing_keys, "bad_rows": bad_rows})
    return {
        "ok_count": ok_count,
        "missing_count": len(missing_keys),
        "mismatch_count": len(bad_rows),
        "missing_keys": missing_keys,
        "bad_rows": bad_rows[:50],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebalance 00_PROJECT_INBOX and 00_TOPIC_INBOX based on confirmed topic removals and method-centric project items."
    )
    parser.add_argument("--review-dir", required=True, help="Directory containing confirm_candidates.jsonl")
    parser.add_argument("--output-dir", default="", help="Write logs under repository log/")
    parser.add_argument("--profile", default="", help="Optional zot profile")
    parser.add_argument("--batch-size", type=int, default=25, help="API update batch size")
    parser.add_argument("--apply", action="store_true", help="Actually update Zotero Web API")
    args = parser.parse_args()

    review_dir = Path(args.review_dir).resolve()
    confirm_path = review_dir / "confirm_candidates.jsonl"
    if not confirm_path.exists():
        raise SystemExit(f"Missing confirmation file: {confirm_path}")

    output_dir = resolve_output_dir(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    approved_rows = iter_jsonl(confirm_path)
    approved_keys = {str(row["key"]) for row in approved_rows}

    client = build_client(args.profile or None)
    path_to_key = fetch_collection_state(client)
    project_key = path_to_key.get(PROJECT_PATH)
    topic_key = path_to_key.get(TOPIC_PATH)
    if not project_key or not topic_key:
        raise SystemExit("Could not resolve 00_PROJECT_INBOX or 00_TOPIC_INBOX from current Zotero collection tree.")

    print(f"[preflight] project_key={project_key} topic_key={topic_key}", flush=True)
    print(f"[preflight] review_dir={review_dir}", flush=True)
    print(f"[preflight] output_dir={output_dir}", flush=True)
    print(f"[preflight] apply={args.apply}", flush=True)

    project_items = fetch_collection_items(client, project_key)
    topic_items = fetch_collection_items(client, topic_key)
    items_by_key = dict(project_items)
    items_by_key.update(topic_items)

    extra_keys = sorted(approved_keys - set(items_by_key))
    if extra_keys:
        items_by_key.update(fetch_items_by_keys(client, extra_keys, batch_size=args.batch_size))

    topic_to_project_ops, missing_approved = build_topic_to_project_ops(
        approved_rows=approved_rows,
        items_by_key=items_by_key,
        project_key=project_key,
        topic_key=topic_key,
    )
    project_to_topic_ops = build_project_to_topic_ops(
        project_items=project_items,
        approved_keys=approved_keys,
        project_key=project_key,
        topic_key=topic_key,
    )

    conflict_keys = sorted({op["key"] for op in topic_to_project_ops} & {op["key"] for op in project_to_topic_ops})
    if conflict_keys:
        topic_to_project_ops = [op for op in topic_to_project_ops if op["key"] not in conflict_keys]
        project_to_topic_ops = [op for op in project_to_topic_ops if op["key"] not in conflict_keys]

    operations = sorted(topic_to_project_ops + project_to_topic_ops, key=lambda op: (op["operation"], op["title"].lower()))
    write_jsonl(output_dir / "topic_to_project_ops.jsonl", topic_to_project_ops)
    write_jsonl(output_dir / "project_to_topic_ops.jsonl", project_to_topic_ops)

    summary = {
        "approved_topic_candidates": len(approved_rows),
        "current_project_items": len(project_items),
        "current_topic_items": len(topic_items),
        "topic_to_project_updates": len(topic_to_project_ops),
        "project_to_topic_updates": len(project_to_topic_ops),
        "conflict_count": len(conflict_keys),
        "missing_approved_count": len(missing_approved),
        "missing_approved_keys": missing_approved[:50],
    }
    write_json(output_dir / "plan_summary.json", summary)

    plan_lines = [
        "# Project/Topic Inbox Rebalance",
        "",
        f"- Approved topic->project candidates loaded: {summary['approved_topic_candidates']}",
        f"- Current project inbox items (Web API): {summary['current_project_items']}",
        f"- Current topic inbox items (Web API): {summary['current_topic_items']}",
        f"- Planned topic->project updates: {summary['topic_to_project_updates']}",
        f"- Planned project->topic updates: {summary['project_to_topic_updates']}",
        f"- Conflicts skipped: {summary['conflict_count']}",
        f"- Approved keys not fetched: {summary['missing_approved_count']}",
        "",
        "Artifacts:",
        "- `topic_to_project_ops.jsonl`",
        "- `project_to_topic_ops.jsonl`",
        "- `apply_results.jsonl`",
        "- `verify_summary.json`",
    ]
    (output_dir / "plan.md").write_text("\n".join(plan_lines) + "\n", encoding="utf-8")

    apply_summary = apply_operations(
        client=client,
        operations=operations,
        items_by_key=items_by_key,
        apply=args.apply,
        output_dir=output_dir,
        batch_size=args.batch_size,
    )
    verify_summary = {}
    if args.apply:
        verify_summary = verify_operations(client=client, operations=operations, batch_size=args.batch_size, output_dir=output_dir)

    write_json(output_dir / "summary.json", {"plan": summary, "apply": apply_summary, "verify": verify_summary})
    print(json.dumps({"ok": True, "output_dir": str(output_dir), "plan": summary, "apply": apply_summary, "verify": verify_summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PyZoteroError, httpx.HTTPError) as exc:
        raise SystemExit(f"Zotero API error: {exc}") from exc

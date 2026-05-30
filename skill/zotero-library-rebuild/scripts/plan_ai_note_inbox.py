from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from zotero_cli_agents.config import get_data_dir, load_config, project_root

PROJECT_INBOX_PATH = "20_PROJECTS/00_PROJECT_INBOX"
TOPIC_INBOX_PATH = "30_TOPICS/00_TOPIC_INBOX"
WORKFLOW_TAG = "workflow/ai_note"
TARGET_PATHS = [PROJECT_INBOX_PATH, TOPIC_INBOX_PATH]

PROJECT_KEYWORDS = {
    "project/mno2": [
        "mno2",
        "mn o2",
        "mn oxide",
        "manganese dioxide",
        "manganese oxide",
        "manganese oxides",
        "birnessite",
        "cryptomelane",
        "todorokite",
        "mn3o7",
        "chalcophanite",
        "二氧化锰",
        "锰氧化物",
    ],
    "project/zn": [
        " zn ",
        "zinc",
        "zn metal",
        "zinc anode",
        "zinc metal",
        "zib",
        "azib",
        "zn/mno2",
        "zn mn",
        "zn//",
        "锌",
        "水系锌",
        "锌离子",
    ],
    "project/battery": [
        "battery",
        "batteries",
        "aqueous battery",
        "energy storage",
        "supercapacitor",
        "anode",
        "cathode",
        "coin cell",
        "lithium ion",
        "li ion",
        "sodium ion",
        "na ion",
        "potassium ion",
        "electrochemical storage",
        "metal sulfur",
        "polysulfide",
        "lithium storage",
        "sodium storage",
        "rechargeable",
        "电池",
        "正极",
        "负极",
        "储能",
        "锂离子",
        "钠离子",
        "钾金属",
        "多硫化物",
    ],
    "project/cellulose": ["cellulose", "nanocellulose", "cellulosic"],
}

TOPIC_KEYWORDS = {
    "topic/academic": [
        "academic writing",
        "citation management",
        "bibliography",
        "scholarly communication",
        "教材",
        "手册",
        "入门参考",
        "学术职业",
        "博士",
    ],
    "topic/coding": [
        "python programming",
        "software development",
        "command line",
        "api client",
        "automation script",
        "software",
        "program",
        "analysis tool",
        "automated analysis",
        "软件",
        "程序",
        "自动化",
        "storyboard",
    ],
    "topic/visualization": [
        "data visualization",
        "scientific visualization",
        "visualization",
        "plotting",
        "成像",
        "tomography",
        "断层扫描",
    ],
    "topic/electrochemistry": [
        "electrochem",
        "voltammetry",
        "impedance",
        "galvanostatic",
        "eis",
        "constant phase element",
        "cpe",
        "mixed potential",
        "nucleation",
        "hydrogen evolution",
        "her",
        "电化学",
        "阻抗",
        "成核",
        "混合电位",
        "水电解",
        "电解池",
    ],
    "topic/characterization": [
        "xas",
        "tem",
        "txm",
        "xrd",
        "xps",
        "sem",
        "raman",
        "ftir",
        "eels",
        "xanes",
        "xes",
        "stxm",
        "spectromicroscopy",
        "stem",
        "epr",
        "elnes",
        "exafs",
        "synchrotron",
        "feff",
        "xafs",
        "spectro-ptychography",
        "ptychography",
        "光谱",
        "谱学",
        "衍射",
        "显微",
        "同步辐射",
        "小波",
        "光谱显微",
        "精修",
        "rietveld",
        "uv-vis",
        "uv vis",
    ],
    "topic/modeling": [
        "dft",
        "molecular dynamics",
        "phase field",
        "modeling",
        "thermodynamic",
        "phase transformation",
        "young laplace",
        "nernst",
        "butler volmer",
        "pca",
        "mcr",
        "mcr als",
        "simplisma",
        "cluster analysis",
        "lvq",
        "理论",
        "模型",
        "拟合",
        "相图",
        "赝势",
        "方程",
        "genetic algorithm",
        "darken",
    ],
    "topic/machine_learning": [
        "machine learning",
        "deep learning",
        "neural network",
        "人工智能",
    ],
    "topic/rag_knowledge": [
        "retrieval augmented generation",
        "retrieval augmented",
        "knowledge base",
        "vector database",
    ],
    "topic/productivity": [
        "productivity system",
        "personal knowledge management",
        "note taking",
        "obsidian",
        "数字信息组织",
        "信息组织",
        "自我管理",
        "para",
    ],
    "topic/finance": [
        "finance",
        "financial market",
        "stock market",
        "bond yield",
        "portfolio",
        "equity market",
        "财富",
        "经济",
        "工业化",
        "政策",
        "社会经济",
    ],
    "topic/history": [
        "historiography",
        "world history",
        "modern history",
        "history of science",
        "历史",
        "史论",
        "传记",
    ],
    "topic/literature": [
        "literary",
        "literary criticism",
        "poetry",
        "fiction",
        "文学",
        "小说",
        "寓言",
        "鲁迅",
    ],
}


@dataclass
class CollectionRow:
    key: str
    path: str


@dataclass
class ItemRow:
    item_key: str
    title: str
    item_type: str
    is_deleted: bool
    collections: list[str]
    collection_paths: list[str]
    tags: list[str]
    doi: str
    citation_key: str
    creators: list[str]
    year: str
    abstract_preview: str


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


def resolve_output_dir(raw_output_dir: str) -> Path:
    root = project_root()
    log_root = (root / "log").resolve()
    run_root = (log_root / "zotero-library-rebuild").resolve()
    raw_path = Path(raw_output_dir)

    if raw_path.is_absolute():
        output_dir = raw_path.resolve()
    elif raw_path.parts and raw_path.parts[0].lower() == "log":
        output_dir = (root / raw_path).resolve()
    else:
        output_dir = (run_root / raw_path).resolve()

    if output_dir == log_root or log_root not in output_dir.parents:
        raise SystemExit(f"Output directory must be under repository log directory: {log_root}")
    return output_dir


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro&immutable=1", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("SELECT 1 FROM items LIMIT 1")
    return conn


def field_id_map(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT fieldID, fieldName FROM fields").fetchall()
    return {row["fieldName"]: row["fieldID"] for row in rows}


def collection_rows(conn: sqlite3.Connection, library_id: int) -> list[CollectionRow]:
    rows = conn.execute(
        """
        SELECT c.collectionID, c.collectionName, c.parentCollectionID, c.key
        FROM collections c
        WHERE c.libraryID = ?
        """,
        (library_id,),
    ).fetchall()
    by_id = {row["collectionID"]: row for row in rows}
    path_cache: dict[int, str] = {}

    def path_for(collection_id: int) -> str:
        if collection_id in path_cache:
            return path_cache[collection_id]
        row = by_id[collection_id]
        parent_id = row["parentCollectionID"]
        if parent_id and parent_id in by_id:
            path = f"{path_for(parent_id)}/{row['collectionName']}"
        else:
            path = row["collectionName"]
        path_cache[collection_id] = path
        return path

    return [
        CollectionRow(key=row["key"], path=path_for(row["collectionID"]))
        for row in sorted(rows, key=lambda value: path_for(value["collectionID"]).lower())
    ]


def item_rows(conn: sqlite3.Connection, library_id: int) -> list[ItemRow]:
    fields = field_id_map(conn)
    excluded_type_ids = tuple(
        row["itemTypeID"]
        for row in conn.execute(
            "SELECT itemTypeID FROM itemTypes WHERE typeName IN ('attachment','note','annotation')"
        ).fetchall()
    )
    if not excluded_type_ids:
        excluded_type_ids = (-1,)

    sql = f"""
    SELECT i.itemID, i.key, it.typeName, CASE WHEN d.itemID IS NULL THEN 0 ELSE 1 END AS isDeleted
    FROM items i
    JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
    JOIN itemTags itt ON itt.itemID = i.itemID
    JOIN tags tg ON tg.tagID = itt.tagID AND tg.name = ?
    LEFT JOIN deletedItems d ON d.itemID = i.itemID
    WHERE i.libraryID = ? AND i.itemTypeID NOT IN ({",".join("?" for _ in excluded_type_ids)})
    ORDER BY i.dateAdded ASC
    """
    base_rows = conn.execute(sql, (WORKFLOW_TAG, library_id, *excluded_type_ids)).fetchall()
    if not base_rows:
        return []

    item_ids = [row["itemID"] for row in base_rows]
    placeholders = ",".join("?" for _ in item_ids)

    wanted_fields = {
        name: fields[name]
        for name in ("title", "abstractNote", "date", "DOI", "citationKey")
        if name in fields
    }
    values_by_item: dict[int, dict[str, str]] = defaultdict(dict)
    if wanted_fields:
        value_rows = conn.execute(
            f"""
            SELECT id.itemID, f.fieldName, iv.value
            FROM itemData id
            JOIN fields f ON f.fieldID = id.fieldID
            JOIN itemDataValues iv ON iv.valueID = id.valueID
            WHERE id.itemID IN ({placeholders})
              AND id.fieldID IN ({",".join("?" for _ in wanted_fields)})
            """,
            (*item_ids, *wanted_fields.values()),
        ).fetchall()
        for row in value_rows:
            values_by_item[row["itemID"]][row["fieldName"]] = row["value"] or ""

    tag_rows = conn.execute(
        f"""
        SELECT it.itemID, t.name
        FROM itemTags it
        JOIN tags t ON t.tagID = it.tagID
        WHERE it.itemID IN ({placeholders})
        """,
        item_ids,
    ).fetchall()
    tags_by_item: dict[int, list[str]] = defaultdict(list)
    for row in tag_rows:
        tags_by_item[row["itemID"]].append(row["name"])

    all_collections = collection_rows(conn, library_id)
    path_by_key = {row.key: row.path for row in all_collections}
    collection_rows_raw = conn.execute(
        f"""
        SELECT ci.itemID, c.key, c.collectionName
        FROM collectionItems ci
        JOIN collections c ON c.collectionID = ci.collectionID
        WHERE ci.itemID IN ({placeholders})
        """,
        item_ids,
    ).fetchall()
    collection_keys_by_item: dict[int, list[str]] = defaultdict(list)
    collection_paths_by_item: dict[int, list[str]] = defaultdict(list)
    for row in collection_rows_raw:
        collection_keys_by_item[row["itemID"]].append(row["key"])
        collection_paths_by_item[row["itemID"]].append(path_by_key.get(row["key"], row["collectionName"]))

    creator_rows = conn.execute(
        f"""
        SELECT ic.itemID, c.firstName, c.lastName
        FROM itemCreators ic
        JOIN creators c ON c.creatorID = ic.creatorID
        WHERE ic.itemID IN ({placeholders})
        ORDER BY ic.itemID, ic.orderIndex
        """,
        item_ids,
    ).fetchall()
    creators_by_item: dict[int, list[str]] = defaultdict(list)
    for row in creator_rows:
        name = " ".join(part for part in (row["firstName"], row["lastName"]) if part)
        if name:
            creators_by_item[row["itemID"]].append(name)

    items: list[ItemRow] = []
    for row in base_rows:
        item_id = row["itemID"]
        values = values_by_item.get(item_id, {})
        raw_date = values.get("date", "")
        year_match = re.search(r"(19|20)\d{2}", raw_date)
        items.append(
            ItemRow(
                item_key=row["key"],
                title=values.get("title", ""),
                item_type=row["typeName"],
                is_deleted=bool(row["isDeleted"]),
                collections=sorted(collection_keys_by_item.get(item_id, [])),
                collection_paths=sorted(collection_paths_by_item.get(item_id, [])),
                tags=sorted(tags_by_item.get(item_id, [])),
                doi=values.get("DOI", ""),
                citation_key=values.get("citationKey", ""),
                creators=creators_by_item.get(item_id, []),
                year=year_match.group(0) if year_match else "",
                abstract_preview=values.get("abstractNote", "")[:1000],
            )
        )
    return items


def normalize_text(item: ItemRow) -> str:
    parts = [
        item.title,
        item.abstract_preview,
        item.doi,
        item.citation_key,
        " ".join(item.creators),
        " ".join(item.tags),
        " ".join(item.collection_paths),
    ]
    return " " + " ".join(parts).lower().replace("-", " ") + " "


def keyword_in_text(keyword: str, text: str) -> bool:
    normalized = " ".join(keyword.lower().replace("-", " ").split())
    if not normalized:
        return False
    pattern = re.escape(normalized).replace(r"\ ", r"\s+")
    return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", text) is not None


def keyword_matches(text: str, mapping: dict[str, list[str]]) -> list[str]:
    hits: list[str] = []
    for tag, keywords in mapping.items():
        if any(keyword_in_text(keyword, text) for keyword in keywords):
            hits.append(tag)
    return sorted(set(hits))


def classify_item(item: ItemRow) -> dict[str, Any]:
    text = normalize_text(item)
    project_tags = keyword_matches(text, PROJECT_KEYWORDS)
    topic_tags = keyword_matches(text, TOPIC_KEYWORDS)
    targets: list[str] = []
    reasons: list[str] = []
    confidence = "medium"
    fallback = False

    if project_tags:
        targets.append(PROJECT_INBOX_PATH)
        reasons.append(f"project signals: {', '.join(project_tags)}")
    if topic_tags:
        targets.append(TOPIC_INBOX_PATH)
        reasons.append(f"topic signals: {', '.join(topic_tags)}")
    if not targets:
        targets.append(TOPIC_INBOX_PATH)
        reasons.append("fallback: workflow/ai_note item without explicit project/topic keyword hit")
        confidence = "low"
        fallback = True

    current_targets = sorted(path for path in item.collection_paths if path in TARGET_PATHS)
    new_targets = sorted(path for path in set(targets) if path not in set(current_targets))

    return {
        "item_key": item.item_key,
        "title": item.title,
        "item_type": item.item_type,
        "current_targets": current_targets,
        "planned_targets": sorted(set(targets)),
        "new_targets": new_targets,
        "project_tags": project_tags,
        "topic_tags": topic_tags,
        "reasons": reasons,
        "confidence": confidence,
        "fallback": fallback,
    }


def target_tree_rows() -> list[dict[str, str | None]]:
    rows = []
    for path in TARGET_PATHS:
        parts = path.split("/")
        rows.append(
            {
                "path": path,
                "name": parts[-1],
                "parent_path": "/".join(parts[:-1]) if len(parts) > 1 else None,
            }
        )
    return rows


def write_plan(output_dir: Path, items: list[ItemRow], classifications: list[dict[str, Any]]) -> None:
    export_dir = output_dir / "00_export_current_state"
    design_dir = output_dir / "30_design_adjustment"
    plan_dir = output_dir / "40_plan_for_confirmation"

    write_jsonl(export_dir / "items_before.jsonl", [asdict(item) for item in items])
    write_jsonl(export_dir / "item_collection_edges.jsonl", [
        {"item_key": item.item_key, "collections": item.collections, "collection_paths": item.collection_paths}
        for item in items
    ])
    write_jsonl(export_dir / "item_tag_edges.jsonl", [
        {"item_key": item.item_key, "tags": item.tags}
        for item in items
    ])

    write_json(design_dir / "target_collection_tree.json", target_tree_rows())

    movement_rows = [
        {
            "phase": "items",
            "item_key": row["item_key"],
            "title": row["title"],
            "from_collections": [],
            "to_collections": row["new_targets"],
            "reason": row["reasons"],
            "confidence": row["confidence"],
            "needs_user_confirm": True,
        }
        for row in classifications
        if row["new_targets"]
    ]
    write_jsonl(plan_dir / "item_movement_plan.jsonl", movement_rows)
    write_jsonl(plan_dir / "archive_item_membership_plan.jsonl", [])
    write_jsonl(plan_dir / "tag_update_plan.jsonl", [])
    write_jsonl(plan_dir / "classification_preview.jsonl", classifications)

    fallback_rows = [row for row in classifications if row["fallback"]]
    low_confidence_lines = [
        "# Low Confidence Items",
        "",
        "These workflow/ai_note items had no explicit project/topic keyword hit and are planned into topic inbox by fallback.",
        "",
    ]
    for row in fallback_rows:
        low_confidence_lines.append(f"- {row['item_key']} | {row['title']}")
    (plan_dir / "low_confidence_items.md").write_text("\n".join(low_confidence_lines) + "\n", encoding="utf-8")

    counts = Counter()
    counts["total_ai_note_items"] = len(items)
    counts["planned_item_updates"] = len(movement_rows)
    counts["planned_project_additions"] = sum(1 for row in classifications if PROJECT_INBOX_PATH in row["new_targets"])
    counts["planned_topic_additions"] = sum(1 for row in classifications if TOPIC_INBOX_PATH in row["new_targets"])
    counts["final_project_memberships"] = sum(1 for row in classifications if PROJECT_INBOX_PATH in row["planned_targets"])
    counts["final_topic_memberships"] = sum(1 for row in classifications if TOPIC_INBOX_PATH in row["planned_targets"])
    counts["dual_membership_items"] = sum(1 for row in classifications if len(row["planned_targets"]) == 2)
    counts["fallback_topic_items"] = len(fallback_rows)
    counts["already_project_memberships"] = sum(1 for row in classifications if PROJECT_INBOX_PATH in row["current_targets"])
    counts["already_topic_memberships"] = sum(1 for row in classifications if TOPIC_INBOX_PATH in row["current_targets"])
    counts["unchanged_items"] = sum(1 for row in classifications if not row["new_targets"])

    summary_payload = {
        "counts": dict(counts),
        "target_paths": TARGET_PATHS,
        "workflow_tag": WORKFLOW_TAG,
    }
    write_json(output_dir / "summary.json", summary_payload)

    summary_lines = [
        "# AI Note Inbox Classification Summary",
        "",
        f"- Total `workflow/ai_note` items: {counts['total_ai_note_items']}",
        f"- Planned item updates: {counts['planned_item_updates']}",
        f"- Planned additions to `{PROJECT_INBOX_PATH}`: {counts['planned_project_additions']}",
        f"- Planned additions to `{TOPIC_INBOX_PATH}`: {counts['planned_topic_additions']}",
        f"- Final project memberships after apply: {counts['final_project_memberships']}",
        f"- Final topic memberships after apply: {counts['final_topic_memberships']}",
        f"- Items ending in both inboxes: {counts['dual_membership_items']}",
        f"- Fallback-to-topic items: {counts['fallback_topic_items']}",
        f"- Already classified items needing no new collection add: {counts['unchanged_items']}",
    ]
    (output_dir / "summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    plan_lines = [
        "# AI Note Inbox Classification Plan",
        "",
        "Scope:",
        f"- Read only items carrying `{WORKFLOW_TAG}`.",
        f"- Add collection memberships only to `{PROJECT_INBOX_PATH}` and `{TOPIC_INBOX_PATH}`.",
        "- Preserve all existing collections and tags; this plan does not remove anything.",
        "",
        "Rules:",
        "- Project and topic are additive, not mutually exclusive.",
        "- Text matching scans title, abstract, DOI, citationKey, creators, tags, and collection paths.",
        "- If no explicit project/topic keyword matches are found, the item falls back to topic inbox so every AI-note item is classified somewhere.",
        "",
        "Review files:",
        "- `40_plan_for_confirmation/item_movement_plan.jsonl`",
        "- `40_plan_for_confirmation/classification_preview.jsonl`",
        "- `40_plan_for_confirmation/low_confidence_items.md`",
        "",
        "Apply hint:",
        "- Use `apply-zotero-library-rebuild.ps1 -Phase items -Apply` against this review dir.",
    ]
    (output_dir / "plan.md").write_text("\n".join(plan_lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan inbox classification for workflow/ai_note items into project/topic inbox collections."
    )
    parser.add_argument("--output-dir", required=True, help="Output directory under repository log/.")
    parser.add_argument("--library-id", type=int, default=1, help="Zotero library ID. Default: 1.")
    parser.add_argument("--data-dir", default="", help="Override Zotero data directory.")
    args = parser.parse_args()

    output_dir = resolve_output_dir(args.output_dir)
    cfg = load_config()
    data_dir = Path(args.data_dir) if args.data_dir else get_data_dir(cfg)
    db_path = data_dir / "zotero.sqlite"
    if not db_path.exists():
        raise SystemExit(f"Zotero database not found: {db_path}")

    conn = connect_readonly(db_path)
    try:
        items = item_rows(conn, args.library_id)
    finally:
        conn.close()

    classifications = [classify_item(item) for item in items]
    write_plan(output_dir, items, classifications)
    print(json.dumps({"ok": True, "output_dir": str(output_dir), "item_count": len(items)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

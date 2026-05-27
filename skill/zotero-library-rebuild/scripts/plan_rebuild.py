from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from zotero_cli_agents.config import get_data_dir, load_config, project_root

TARGET_COLLECTION_PATHS = [
    "00_INBOX",
    "00_INBOX/00_UNSORTED",
    "00_INBOX/10_AUTHOR_WATCH",
    "00_INBOX/10_AUTHOR_WATCH/A.P. Hitchcock",
    "00_INBOX/10_AUTHOR_WATCH/Martin Winter",
    "00_INBOX/10_AUTHOR_WATCH/Zaiping Guo",
    "00_INBOX/10_AUTHOR_WATCH/Xiaobo Ji",
    "10_STAGE",
    "10_STAGE/00_SCREENED",
    "10_STAGE/10_AUTHOR_WATCH",
    "20_PROJECTS",
    "20_PROJECTS/00_PROJECT_INBOX",
    "20_PROJECTS/10_MnO2",
    "20_PROJECTS/10_MnO2/00_Reviews",
    "20_PROJECTS/10_MnO2/10_Key_Papers",
    "20_PROJECTS/10_MnO2/20_Theory",
    "20_PROJECTS/10_MnO2/30_Synthesis",
    "20_PROJECTS/10_MnO2/40_Characterization",
    "20_PROJECTS/10_MnO2/50_Mechanism",
    "20_PROJECTS/10_MnO2/60_Performance",
    "20_PROJECTS/10_MnO2/70_Supplementary",
    "20_PROJECTS/10_MnO2/80_Ideas",
    "20_PROJECTS/20_Zn",
    "20_PROJECTS/20_Zn/00_Reviews",
    "20_PROJECTS/20_Zn/10_Key_Papers",
    "20_PROJECTS/20_Zn/20_Theory",
    "20_PROJECTS/20_Zn/30_Synthesis",
    "20_PROJECTS/20_Zn/40_Characterization",
    "20_PROJECTS/20_Zn/50_Mechanism",
    "20_PROJECTS/20_Zn/60_Performance",
    "20_PROJECTS/20_Zn/70_Supplementary",
    "20_PROJECTS/20_Zn/80_Ideas",
    "20_PROJECTS/30_Battery",
    "20_PROJECTS/40_Cellulose",
    "20_PROJECTS/90_Other",
    "30_TOPICS",
    "30_TOPICS/00_TOPIC_INBOX",
    "30_TOPICS/05_Academic",
    "30_TOPICS/10_Coding",
    "30_TOPICS/15_Visualization",
    "30_TOPICS/20_Electrochemistry",
    "30_TOPICS/25_Characterization",
    "30_TOPICS/30_Modeling",
    "30_TOPICS/35_Machine_Learning",
    "30_TOPICS/40_RAG_Knowledge",
    "30_TOPICS/45_Productivity",
    "30_TOPICS/50_Finance",
    "30_TOPICS/55_History",
    "30_TOPICS/60_Literature",
    "40_WORKSPACE",
    "80_TRASH",
    "90_ARCHIVE",
]


PROJECT_KEYWORDS = {
    "project/mno2": [
        "mno2",
        "mn o2",
        "manganese dioxide",
        "manganese oxide",
        "birnessite",
        "cryptomelane",
        "todorokite",
    ],
    "project/zn": [
        " zn ",
        "zinc",
        "zn metal",
        "zinc anode",
        "zinc metal",
    ],
    "project/battery": [
        "battery",
        "batteries",
        "aqueous battery",
        "energy storage",
        "supercapacitor",
    ],
    "project/cellulose": [
        "cellulose",
        "nanocellulose",
        "cellulosic",
    ],
}


TOPIC_KEYWORDS = {
    "topic/academic": ["academic writing", "citation management", "bibliography", "scholarly communication"],
    "topic/coding": [
        "python programming",
        "software development",
        "command line",
        "api client",
        "automation script",
    ],
    "topic/visualization": ["data visualization", "scientific visualization", "visualization", "plotting"],
    "topic/electrochemistry": ["electrochem", "voltammetry", "impedance", "galvanostatic"],
    "topic/characterization": ["xas", "tem", "txm", "xrd", "xps", "sem", "raman", "ftir"],
    "topic/modeling": ["dft", "molecular dynamics", "phase field", "modeling"],
    "topic/machine_learning": ["machine learning", "deep learning", "neural network"],
    "topic/rag_knowledge": [
        "retrieval augmented generation",
        "retrieval augmented",
        "knowledge base",
        "vector database",
    ],
    "topic/productivity": ["productivity system", "personal knowledge management", "note taking", "obsidian"],
    "topic/finance": ["finance", "financial market", "stock market", "bond yield", "portfolio", "equity market"],
    "topic/history": ["historiography", "world history", "modern history", "history of science"],
    "topic/literature": ["literary", "literary criticism", "poetry", "fiction"],
}


TECH_KEYWORDS = {
    "tech/electrochemistry/cv": ["cyclic voltammetry", "cyclic voltammogram", "cv curve", "cv curves"],
    "tech/electrochemistry/gcd": ["gcd", "galvanostatic", "charge-discharge", "charge discharge"],
    "tech/electrochemistry/eis": ["eis", "impedance"],
    "tech/electrochemistry/dqdv": ["dq/dv", "dqdv", "differential capacity"],
    "tech/electrochemistry/lsv": ["lsv", "linear sweep"],
    "tech/electrochemistry/ocv": ["ocv", "open-circuit", "open circuit"],
    "tech/electrochemistry/ca": ["chronoamperometry", "chronoamperometric", "ca curve", "ca curves"],
    "tech/electrochemistry/cp": ["chronopotentiometry", "chronopotentiometric", "cp curve", "cp curves"],
    "tech/electrochemistry/cycling": ["cycling performance", "cycle life"],
    "tech/electrochemistry/rate_capability": ["rate capability", "rate performance"],
    "tech/characterization/xas": ["xas", "x-ray absorption", "x ray absorption"],
    "tech/characterization/exafs": ["exafs"],
    "tech/characterization/tem": ["tem", "transmission electron"],
    "tech/characterization/txm": ["txm", "transmission x-ray microscopy", "transmission x ray microscopy"],
    "tech/characterization/xrd": ["xrd", "x-ray diffraction", "x ray diffraction"],
    "tech/characterization/xps": ["xps", "photoelectron"],
    "tech/characterization/sem": ["sem", "scanning electron"],
    "tech/characterization/raman": ["raman"],
    "tech/characterization/ftir": ["ftir", "fourier transform infrared"],
    "tech/modeling/dft": ["dft", "density functional"],
    "tech/modeling/md": ["molecular dynamics"],
    "tech/modeling/phase_field": ["phase field"],
    "tech/ai/machine_learning": ["machine learning", "deep learning", "neural network"],
    "tech/ai/rag": ["rag", "retrieval augmented"],
    "tech/ai/llm_agent": ["llm", "large language model", "language model agent", "ai agent", "multi agent"],
}


LEGACY_TAG_CONVERSIONS = {
    "update/metadata": "workflow/metadata_cleaned",
    "update/AInote": "workflow/ai_note",
    "/reading": "status/reading",
}

LEGACY_TOP_LEVELS = {
    "00_INBOX_AA",
    "00_INBOX_BB",
    "01_SHORTTERMS",
    "02_PROJECTS",
    "03_AREAS",
    "04_TRASH",
}

TARGET_ITEM_PREFIXES = (
    "00_INBOX/",
    "10_STAGE/",
    "20_PROJECTS/",
    "30_TOPICS/",
)

TARGET_ITEM_PATHS = {"80_TRASH"}


EXCLUDED_TYPES = ("attachment", "note", "annotation")

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "abstract",
    "also",
    "based",
    "be",
    "been",
    "by",
    "can",
    "could",
    "for",
    "from",
    "has",
    "have",
    "here",
    "herein",
    "high",
    "however",
    "in",
    "into",
    "is",
    "its",
    "may",
    "not",
    "of",
    "on",
    "one",
    "or",
    "our",
    "the",
    "their",
    "these",
    "they",
    "this",
    "those",
    "to",
    "toward",
    "towards",
    "sub",
    "sup",
    "such",
    "than",
    "that",
    "there",
    "through",
    "using",
    "used",
    "via",
    "was",
    "were",
    "which",
    "while",
    "with",
}


@dataclass
class CollectionRow:
    key: str
    name: str
    parent_key: str | None
    path: str
    item_count: int


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
    creators: list[str]
    year: str
    abstract_preview: str
    has_pdf: bool
    has_notes: bool


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro&immutable=1", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("SELECT 1 FROM items LIMIT 1")
    return conn


def get_excluded_type_ids(conn: sqlite3.Connection) -> tuple[int, ...]:
    placeholders = ",".join("?" for _ in EXCLUDED_TYPES)
    rows = conn.execute(
        f"SELECT itemTypeID FROM itemTypes WHERE typeName IN ({placeholders})",
        EXCLUDED_TYPES,
    ).fetchall()
    return tuple(row["itemTypeID"] for row in rows) or (-1,)


def field_id_map(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT fieldID, fieldName FROM fields").fetchall()
    return {row["fieldName"]: row["fieldID"] for row in rows}


def collection_rows(conn: sqlite3.Connection, library_id: int) -> list[CollectionRow]:
    rows = conn.execute(
        """
        SELECT c.collectionID, c.collectionName, c.parentCollectionID, c.key,
               COUNT(ci.itemID) AS item_count
        FROM collections c
        LEFT JOIN collectionItems ci ON ci.collectionID = c.collectionID
        WHERE c.libraryID = ?
        GROUP BY c.collectionID, c.collectionName, c.parentCollectionID, c.key
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

    key_by_id = {row["collectionID"]: row["key"] for row in rows}
    output = []
    for row in rows:
        parent_id = row["parentCollectionID"]
        output.append(
            CollectionRow(
                key=row["key"],
                name=row["collectionName"],
                parent_key=key_by_id.get(parent_id),
                path=path_for(row["collectionID"]),
                item_count=int(row["item_count"]),
            )
        )
    return sorted(output, key=lambda c: c.path.lower())


def item_rows(conn: sqlite3.Connection, library_id: int, limit: int | None = None) -> list[ItemRow]:
    excluded_ids = get_excluded_type_ids(conn)
    excluded = ",".join("?" for _ in excluded_ids)
    params: list[Any] = list(excluded_ids)
    sql = (
        "SELECT i.itemID, i.key, it.typeName, CASE WHEN d.itemID IS NULL THEN 0 ELSE 1 END AS isDeleted "
        "FROM items i JOIN itemTypes it ON it.itemTypeID = i.itemTypeID "
        "LEFT JOIN deletedItems d ON d.itemID = i.itemID "
        f"WHERE i.itemTypeID NOT IN ({excluded}) AND i.libraryID = ? "
        "ORDER BY i.dateAdded ASC"
    )
    params.append(library_id)
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    base_rows = conn.execute(sql, params).fetchall()
    if not base_rows:
        return []
    item_ids = [row["itemID"] for row in base_rows]
    placeholders = ",".join("?" for _ in item_ids)
    fields = field_id_map(conn)
    wanted_fields = {name: fields[name] for name in ("title", "abstractNote", "date", "DOI") if name in fields}

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
        FROM itemTags it JOIN tags t ON t.tagID = it.tagID
        WHERE it.itemID IN ({placeholders})
        """,
        item_ids,
    ).fetchall()
    tags_by_item: dict[int, list[str]] = defaultdict(list)
    for row in tag_rows:
        tags_by_item[row["itemID"]].append(row["name"])

    coll_rows = conn.execute(
        f"""
        SELECT ci.itemID, c.key, c.collectionID, c.collectionName, c.parentCollectionID
        FROM collectionItems ci
        JOIN collections c ON c.collectionID = ci.collectionID
        WHERE ci.itemID IN ({placeholders})
        """,
        item_ids,
    ).fetchall()
    all_collections = collection_rows(conn, library_id)
    path_by_key = {coll.key: coll.path for coll in all_collections}
    collections_by_item: dict[int, list[str]] = defaultdict(list)
    collection_paths_by_item: dict[int, list[str]] = defaultdict(list)
    for row in coll_rows:
        collections_by_item[row["itemID"]].append(row["key"])
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

    pdf_rows = conn.execute(
        f"""
        SELECT DISTINCT parentItemID
        FROM itemAttachments
        WHERE parentItemID IN ({placeholders})
          AND contentType = 'application/pdf'
        """,
        item_ids,
    ).fetchall()
    pdf_items = {row["parentItemID"] for row in pdf_rows}

    note_rows = conn.execute(
        f"SELECT DISTINCT parentItemID FROM itemNotes WHERE parentItemID IN ({placeholders})",
        item_ids,
    ).fetchall()
    note_items = {row["parentItemID"] for row in note_rows}

    output = []
    for row in base_rows:
        values = values_by_item.get(row["itemID"], {})
        date_text = values.get("date", "")
        year_match = re.search(r"(19|20)\d{2}", date_text)
        abstract = values.get("abstractNote", "")
        output.append(
            ItemRow(
                item_key=row["key"],
                title=values.get("title", ""),
                item_type=row["typeName"],
                is_deleted=bool(row["isDeleted"]),
                collections=sorted(collections_by_item.get(row["itemID"], [])),
                collection_paths=sorted(collection_paths_by_item.get(row["itemID"], [])),
                tags=sorted(tags_by_item.get(row["itemID"], [])),
                doi=values.get("DOI", ""),
                creators=creators_by_item.get(row["itemID"], []),
                year=year_match.group(0) if year_match else "",
                abstract_preview=abstract[:500],
                has_pdf=row["itemID"] in pdf_items,
                has_notes=row["itemID"] in note_items,
            )
        )
    return output


def count_parent_items(conn: sqlite3.Connection, library_id: int) -> int:
    excluded_ids = get_excluded_type_ids(conn)
    excluded = ",".join("?" for _ in excluded_ids)
    row = conn.execute(
        f"SELECT COUNT(*) AS count FROM items WHERE itemTypeID NOT IN ({excluded}) AND libraryID = ?",
        (*excluded_ids, library_id),
    ).fetchone()
    return int(row["count"])


def tag_counts(conn: sqlite3.Connection, library_id: int) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT t.name, COUNT(*) AS count
        FROM itemTags it
        JOIN tags t ON t.tagID = it.tagID
        JOIN items i ON i.itemID = it.itemID
        WHERE i.libraryID = ?
        GROUP BY t.name
        ORDER BY count DESC, t.name COLLATE NOCASE
        """,
        (library_id,),
    ).fetchall()
    return {row["name"]: int(row["count"]) for row in rows}


def normalize_text(item: ItemRow) -> str:
    parts = [
        item.title,
        item.abstract_preview,
        item.doi,
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
    matched = []
    for tag, keywords in mapping.items():
        for keyword in keywords:
            if keyword_in_text(keyword, text):
                matched.append(tag)
                break
    return matched


def legacy_tag_conversions(item: ItemRow) -> tuple[list[str], list[str]]:
    tags: list[str] = []
    reasons: list[str] = []
    for old_tag, new_tag in LEGACY_TAG_CONVERSIONS.items():
        if old_tag in item.tags:
            tags.append(new_tag)
            reasons.append(f"legacy tag conversion: {old_tag} -> {new_tag}")
    return tags, reasons


def legacy_tail(path: str) -> str:
    parts = path.split("/")
    for index, part in enumerate(parts):
        if part in LEGACY_TOP_LEVELS:
            return "/".join(parts[index:])
    return path


def is_legacy_trash_path(path: str) -> bool:
    return legacy_tail(path).split("/")[0] == "04_TRASH"


def existing_target_paths(paths: list[str]) -> list[str]:
    targets = []
    for path in paths:
        if path in TARGET_ITEM_PATHS or any(path.startswith(prefix) for prefix in TARGET_ITEM_PREFIXES):
            targets.append(path)
    return targets


def classify_item(item: ItemRow, archive_uncertain_path: str) -> tuple[list[str], list[str], list[str], str, list[str]]:
    paths = item.collection_paths
    legacy_paths = [legacy_tail(path) for path in paths]
    text = normalize_text(item)
    reasons: list[str] = []
    targets: list[str] = existing_target_paths(paths)
    tags: list[str] = []
    confidence = "medium"
    converted_tags, conversion_reasons = legacy_tag_conversions(item)
    tags.extend(converted_tags)
    reasons.extend(conversion_reasons)

    if any(is_legacy_trash_path(path) for path in paths):
        return ["80_TRASH"], sorted(set(tags)), reasons + ["legacy 04_TRASH collection"], "high", []

    if targets:
        reasons.append("existing target collection membership")

    author_paths = [path for path in legacy_paths if path.startswith("00_INBOX_AA/")]
    if author_paths:
        targets.extend([f"00_INBOX/10_AUTHOR_WATCH/{path.rsplit('/', 1)[-1]}" for path in author_paths])
        targets.append("00_INBOX/00_UNSORTED")
        reasons.append("legacy author-watch inbox collection")

    if any(path == "00_INBOX_AA" or path == "00_INBOX_BB" for path in legacy_paths):
        targets.append("00_INBOX/00_UNSORTED")
        reasons.append("legacy inbox collection")

    if any(path.startswith("01_SHORTTERMS") for path in legacy_paths):
        targets.append("10_STAGE/00_SCREENED")
        reasons.append("legacy short-term screened collection")

    if any(path.startswith("02_PROJECTS") for path in legacy_paths):
        targets.append("20_PROJECTS/00_PROJECT_INBOX")
        reasons.append("legacy project collection")

    if any(path.startswith("03_AREAS") for path in legacy_paths):
        targets.append("30_TOPICS/00_TOPIC_INBOX")
        reasons.append("legacy area/topic collection")

    project_tags = keyword_matches(text, PROJECT_KEYWORDS)
    topic_tags = keyword_matches(text, TOPIC_KEYWORDS)
    tech_tags = keyword_matches(text, TECH_KEYWORDS)

    tags.extend(project_tags)
    tags.extend(topic_tags)
    tags.extend(tech_tags)

    if project_tags and "20_PROJECTS/00_PROJECT_INBOX" not in targets:
        targets.append("20_PROJECTS/00_PROJECT_INBOX")
        reasons.append("project keyword match")
    if topic_tags and not project_tags and "30_TOPICS/00_TOPIC_INBOX" not in targets:
        targets.append("30_TOPICS/00_TOPIC_INBOX")
        reasons.append("topic keyword match")

    if not targets:
        reasons.append("no confident legacy mapping")
        confidence = "low"

    if len(set(targets)) > 3:
        confidence = "low"
    elif project_tags or topic_tags or author_paths or targets:
        confidence = "medium"

    if confidence == "low":
        targets = [archive_uncertain_path]
        tags = sorted(set(converted_tags + ["workflow/needs_manual_review"]))
        reasons.append("uncertain classification preserved in archive for manual review")

    return sorted(set(targets)), sorted(set(tags)), reasons, confidence, sorted(set(project_tags + topic_tags))


def target_tree_rows() -> list[dict[str, str | None]]:
    rows = []
    for path in TARGET_COLLECTION_PATHS:
        parts = path.split("/")
        rows.append(
            {
                "path": path,
                "name": parts[-1],
                "parent_path": "/".join(parts[:-1]) if len(parts) > 1 else None,
            }
        )
    return rows


def target_collection_create_plan(collections: list[CollectionRow]) -> list[dict[str, Any]]:
    existing_paths = {coll.path for coll in collections}
    rows = []
    for row in target_tree_rows():
        path = str(row["path"])
        rows.append(
            {
                **row,
                "action": "use_existing" if path in existing_paths else "create",
                "reason": "target path already exists" if path in existing_paths else "missing target path",
            }
        )
    return rows


def archive_plan(collections: list[CollectionRow], archive_root: str) -> list[dict[str, Any]]:
    existing_paths = {coll.path for coll in collections}
    rows: list[dict[str, Any]] = [
        {
            "old_key": None,
            "old_path": None,
            "archive_path": "90_ARCHIVE",
            "item_count": None,
            "action": "use_existing" if "90_ARCHIVE" in existing_paths else "create",
        },
        {
            "old_key": None,
            "old_path": None,
            "archive_path": archive_root,
            "item_count": None,
            "action": "create",
        },
        {
            "old_key": None,
            "old_path": None,
            "archive_path": f"{archive_root}/00_UNCOLLECTED",
            "item_count": None,
            "action": "create_if_needed",
        },
        {
            "old_key": None,
            "old_path": None,
            "archive_path": f"{archive_root}/00_UNSURE_MANUAL_REVIEW",
            "item_count": None,
            "action": "create_if_needed",
        },
    ]
    rows.extend(
        {
            "old_key": coll.key,
            "old_path": coll.path,
            "archive_path": f"{archive_root}/{coll.path}",
            "item_count": coll.item_count,
            "action": "move_or_recreate_under_archive",
        }
        for coll in collections
        if not coll.path.startswith("90_ARCHIVE")
    )
    return rows


def archive_item_membership_rows(items: list[ItemRow], archive_root: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        if item.is_deleted:
            continue
        if not item.collection_paths:
            rows.append(
                {
                    "phase": "archive_legacy_membership",
                    "item_key": item.item_key,
                    "title": item.title,
                    "from_collection": None,
                    "archive_collection": f"{archive_root}/00_UNCOLLECTED",
                    "reason": ["item has no current collection"],
                    "needs_user_confirm": True,
                }
            )
            continue
        for collection_path in item.collection_paths:
            if collection_path.startswith("90_ARCHIVE"):
                continue
            rows.append(
                {
                    "phase": "archive_legacy_membership",
                    "item_key": item.item_key,
                    "title": item.title,
                    "from_collection": collection_path,
                    "archive_collection": f"{archive_root}/{collection_path}",
                    "reason": ["preserve current collection membership before rebuild"],
                    "needs_user_confirm": True,
                }
            )
    return rows


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def stage_dirs(output_dir: Path) -> dict[str, Path]:
    stages = {
        "00_export_current_state": output_dir / "00_export_current_state",
        "10_extract_library_signals": output_dir / "10_extract_library_signals",
        "20_ai_keyword_tag_review": output_dir / "20_ai_keyword_tag_review",
        "30_design_adjustment": output_dir / "30_design_adjustment",
        "40_plan_for_confirmation": output_dir / "40_plan_for_confirmation",
        "50_execution_results": output_dir / "50_execution_results",
    }
    for path in stages.values():
        path.mkdir(parents=True, exist_ok=True)
    return stages


def item_collection_edges(items: list[ItemRow]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        if not item.collection_paths:
            rows.append({"item_key": item.item_key, "collection_path": None})
            continue
        for collection_path in item.collection_paths:
            rows.append({"item_key": item.item_key, "collection_path": collection_path})
    return rows


def item_tag_edges(items: list[ItemRow]) -> list[dict[str, str]]:
    rows = []
    for item in items:
        for tag in item.tags:
            rows.append({"item_key": item.item_key, "tag": tag})
    return rows


def tokenize(text: str) -> list[str]:
    clean = re.sub(r"<[^>]+>", " ", html.unescape(text))
    return [
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9]{2,}", clean.lower())
        if token not in STOPWORDS and not token.isdigit()
    ]


def build_collection_profiles(items: list[ItemRow], *, title_sample_size: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[ItemRow]] = defaultdict(list)
    for item in items:
        paths = item.collection_paths or ["00_UNCOLLECTED"]
        for path in paths:
            grouped[path].append(item)

    profiles = []
    for path, grouped_items in sorted(grouped.items(), key=lambda kv: kv[0].lower()):
        type_counts = Counter(item.item_type for item in grouped_items)
        tag_counts = Counter(tag for item in grouped_items for tag in item.tags)
        year_counts = Counter(item.year for item in grouped_items if item.year)
        term_counts = Counter(token for item in grouped_items for token in tokenize(f"{item.title} {item.abstract_preview}"))
        profiles.append(
            {
                "collection_path": path,
                "item_count": len(grouped_items),
                "type_counts": dict(type_counts.most_common()),
                "top_existing_tags": dict(tag_counts.most_common(20)),
                "year_counts": dict(year_counts.most_common(20)),
                "top_terms": dict(term_counts.most_common(40)),
                "title_sample": [
                    {
                        "item_key": item.item_key,
                        "title": item.title,
                        "year": item.year,
                        "creators": item.creators[:5],
                        "tags": item.tags,
                    }
                    for item in grouped_items[:title_sample_size]
                ],
            }
        )
    return profiles


def build_collection_title_sets(items: list[ItemRow]) -> list[dict[str, Any]]:
    grouped: dict[str, list[ItemRow]] = defaultdict(list)
    for item in items:
        paths = item.collection_paths or ["00_UNCOLLECTED"]
        for path in paths:
            grouped[path].append(item)
    rows = []
    for path, grouped_items in sorted(grouped.items(), key=lambda kv: kv[0].lower()):
        rows.append(
            {
                "collection_path": path,
                "item_count": len(grouped_items),
                "titles": [
                    {
                        "item_key": item.item_key,
                        "title": item.title,
                        "item_type": item.item_type,
                        "year": item.year,
                        "tags": item.tags,
                    }
                    for item in grouped_items
                ],
            }
        )
    return rows


def build_trash_delete_candidates(items: list[ItemRow]) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        reasons: list[str] = []
        if item.is_deleted:
            reasons.append("already in Zotero built-in trash")
        if any(is_legacy_trash_path(path) for path in item.collection_paths):
            reasons.append("already in legacy 04_TRASH collection")
        if reasons:
            rows.append(
                {
                    "item_key": item.item_key,
                    "title": item.title,
                    "item_type": item.item_type,
                    "is_deleted": item.is_deleted,
                    "current_collections": item.collection_paths,
                    "current_tags": item.tags,
                    "proposed_action": "delete_candidate_after_explicit_user_approval",
                    "reason": reasons,
                }
            )
    return rows


def write_signal_summary(path: Path, profiles: list[dict[str, Any]], trash_count: int) -> None:
    lines = [
        "# Library Signal Summary",
        "",
        f"- Trash delete candidates: {trash_count}",
        f"- Profiled collection/title groups: {len(profiles)}",
        "",
        "## Collection Profiles",
        "",
    ]
    for profile in profiles:
        lines.append(f"### {profile['collection_path']}")
        lines.append("")
        lines.append(f"- items: {profile['item_count']}")
        top_terms = ", ".join(f"{term}({count})" for term, count in list(profile["top_terms"].items())[:20])
        if top_terms:
            lines.append(f"- top terms: {top_terms}")
        top_tags = ", ".join(f"{tag}({count})" for tag, count in list(profile["top_existing_tags"].items())[:10])
        if top_tags:
            lines.append(f"- existing tags: {top_tags}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def read_agent_template(name: str) -> str:
    template_path = Path(__file__).resolve().parents[1] / "agents" / name
    if not template_path.exists():
        raise FileNotFoundError(f"Agent prompt template not found: {template_path}")
    return template_path.read_text(encoding="utf-8")


def write_ai_prompt_files(stage_path: Path) -> None:
    keyword_prompt = read_agent_template("keyword_tag_extraction_prompt.md")
    architecture_prompt = """# AI Prompt: Collection And Tag Architecture Adjustment

Compare the exported library signals with the bundled design references. Decide whether the current collection/tag framework needs adjustment before execution.

Input files:

- `../10_extract_library_signals/signal_summary.md`
- `../10_extract_library_signals/collection_profiles.json`
- `../../../../skill/zotero-library-rebuild/references/collection-design.md`
- `../../../../skill/zotero-library-rebuild/references/tag-taxonomy.md`

Return concise Markdown with:

1. Collection tree changes to make before execution.
2. Tag taxonomy changes to make before execution.
3. Legacy tag conversions that should be deterministic workflow/status additions.
4. Keyword rules that are safe to automate.
5. Keyword rules that must stay manual.
6. Open questions for the user.

Do not propose live Zotero writes.
"""
    plan_review_prompt = """# AI Prompt: Human Plan Review Before Zotero Writes

Review the generated rebuild plan for risky movements and tag assignments.

Input files:

- `../40_plan_for_confirmation/plan_review.md`
- `../40_plan_for_confirmation/item_movement_plan.jsonl`
- `../40_plan_for_confirmation/tag_update_plan.jsonl`
- `../40_plan_for_confirmation/low_confidence_items.md`

Return Markdown with:

1. Items or groups that should stay in `90_ARCHIVE/00_PRE_REBUILD_<date>/00_UNSURE_MANUAL_REVIEW`.
2. Legacy workflow/status tag conversions that look wrong or should be delayed.
3. Tags that are too broad or risky.
4. Collection moves that should be blocked until manual review.
5. A short approval checklist for the user.
"""
    (stage_path / "keyword_tag_extraction_prompt.md").write_text(keyword_prompt, encoding="utf-8")
    (stage_path / "architecture_adjustment_prompt.md").write_text(architecture_prompt, encoding="utf-8")
    (stage_path / "plan_review_prompt.md").write_text(plan_review_prompt, encoding="utf-8")


def write_summary(
    path: Path,
    *,
    db_path: Path,
    output_dir: Path,
    items: list[ItemRow],
    movement_rows: list[dict[str, Any]],
    tag_rows: list[dict[str, Any]],
    collections: list[CollectionRow],
) -> None:
    confidence_counts = Counter(row["confidence"] for row in movement_rows)
    target_counts = Counter(target for row in movement_rows for target in row["to_collections"])
    tag_counts = Counter(tag for row in tag_rows for tag in row["proposed_add_tags"])
    lines = [
        "# Zotero Library Rebuild Dry Run Summary",
        "",
        f"- Database: `{db_path}`",
        f"- Output directory: `{output_dir}`",
        f"- Collections scanned: {len(collections)}",
        f"- Items scanned: {len(items)}",
        f"- Movement rows: {len(movement_rows)}",
        f"- Tag update rows: {len(tag_rows)}",
        "",
        "## Stage Folders",
        "",
        "- `00_export_current_state/`: all items, collections, tags, and relationship edges",
        "- `10_extract_library_signals/`: trash candidates, collection profiles, title sets",
        "- `20_ai_keyword_tag_review/`: prompt files for keyword/tag and architecture review",
        "- `30_design_adjustment/`: target collection tree and design adjustment notes",
        "- `40_plan_for_confirmation/`: archive, movement, and tag plans for human approval",
        "- `50_execution_results/`: reserved for confirmed live-write results",
        "",
        "## Movement Confidence",
        "",
    ]
    for key in ("high", "medium", "low"):
        lines.append(f"- {key}: {confidence_counts.get(key, 0)}")
    lines.extend(["", "## Top Target Collections", ""])
    for target, count in target_counts.most_common(20):
        lines.append(f"- `{target}`: {count}")
    lines.extend(["", "## Top Proposed Tags", ""])
    for tag, count in tag_counts.most_common(30):
        lines.append(f"- `{tag}`: {count}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_movement_summary(path: Path, movement_rows: list[dict[str, Any]]) -> None:
    confidence_counts = Counter(row["confidence"] for row in movement_rows)
    target_counts = Counter(target for row in movement_rows for target in row["to_collections"])
    lines = ["# Movement Summary", "", "## Confidence", ""]
    for key in ("high", "medium", "low"):
        lines.append(f"- {key}: {confidence_counts.get(key, 0)}")
    lines.extend(["", "## Target Collections", ""])
    for target, count in target_counts.most_common():
        lines.append(f"- `{target}`: {count}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_tag_summary(path: Path, tag_rows: list[dict[str, Any]]) -> None:
    confidence_counts = Counter(row["confidence"] for row in tag_rows)
    add_counts = Counter(tag for row in tag_rows for tag in row["proposed_add_tags"])
    no_add_count = sum(1 for row in tag_rows if not row["proposed_add_tags"])
    lines = [
        "# Tag Summary",
        "",
        "## Confidence",
        "",
    ]
    for key in ("high", "medium", "low"):
        lines.append(f"- {key}: {confidence_counts.get(key, 0)}")
    lines.extend(["", f"- rows without proposed new tags: {no_add_count}", "", "## Proposed Add Tags", ""])
    for tag, count in add_counts.most_common():
        lines.append(f"- `{tag}`: {count}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_plan_md(
    path: Path,
    *,
    db_path: Path,
    output_dir: Path,
    archive_root: str,
    archive_uncertain_path: str,
    items: list[ItemRow],
    movement_rows: list[dict[str, Any]],
    tag_rows: list[dict[str, Any]],
    trash_candidate_count: int,
) -> None:
    confidence_counts = Counter(row["confidence"] for row in movement_rows)
    target_counts = Counter(target for row in movement_rows for target in row["to_collections"])
    tag_counts = Counter(tag for row in tag_rows for tag in row["proposed_add_tags"])
    no_tag_count = sum(1 for row in tag_rows if not row["proposed_add_tags"])

    def relative(path_value: Path) -> str:
        return path_value.as_posix()

    lines = [
        "# Zotero Library Rebuild Plan",
        "",
        "This is the human review entrypoint for the dry-run. No live Zotero writes were executed.",
        "",
        "## Scope",
        "",
        f"- Database: `{db_path}`",
        f"- Output directory: `{output_dir}`",
        f"- Items scanned: {len(items)}",
        f"- Movement rows: {len(movement_rows)}",
        f"- Tag update rows: {len(tag_rows)}",
        f"- Trash delete candidates: {trash_candidate_count}",
        f"- Archive root: `{archive_root}`",
        f"- Uncertain item target: `{archive_uncertain_path}`",
        "",
        "## Review Files",
        "",
        f"- Current collection tree: `{relative(Path('00_export_current_state/collection_tree_before.json'))}`",
        f"- Current tags: `{relative(Path('00_export_current_state/tags_before.json'))}`",
        f"- Collection profiles: `{relative(Path('10_extract_library_signals/collection_profiles.json'))}`",
        f"- Signal summary: `{relative(Path('10_extract_library_signals/signal_summary.md'))}`",
        f"- Target collection tree: `{relative(Path('30_design_adjustment/target_collection_tree.json'))}`",
        f"- Movement summary: `{relative(Path('40_plan_for_confirmation/movement_summary.md'))}`",
        f"- Tag summary: `{relative(Path('40_plan_for_confirmation/tag_summary.md'))}`",
        f"- Low-confidence items: `{relative(Path('40_plan_for_confirmation/low_confidence_items.md'))}`",
        f"- Full movement plan: `{relative(Path('40_plan_for_confirmation/item_movement_plan.jsonl'))}`",
        f"- Full tag plan: `{relative(Path('40_plan_for_confirmation/tag_update_plan.jsonl'))}`",
        f"- Legacy archive plan: `{relative(Path('40_plan_for_confirmation/archive_collection_plan.json'))}`",
        "",
        "## Movement Confidence",
        "",
    ]
    for key in ("high", "medium", "low"):
        lines.append(f"- {key}: {confidence_counts.get(key, 0)}")
    lines.extend(["", "## Target Collection Counts", ""])
    for target, count in target_counts.most_common(20):
        lines.append(f"- `{target}`: {count}")
    lines.extend(["", "## Proposed Tag Counts", ""])
    lines.append(f"- rows without proposed new tags: {no_tag_count}")
    for tag, count in tag_counts.most_common(30):
        lines.append(f"- `{tag}`: {count}")
    lines.extend(
        [
            "",
            "## Approval Checklist",
            "",
            "- Confirm the target collection tree is correct.",
            "- Review low-confidence items before any live write.",
            "- Confirm deterministic legacy tag conversions: `update/metadata` -> `workflow/metadata_cleaned`, `update/AInote` -> `workflow/ai_note`, `/reading` -> `status/reading`.",
            "- Review proposed tags for overly broad keyword rules.",
            "- Confirm whether legacy `04_TRASH` should only move to `80_TRASH` or also become permanent-delete candidates.",
            "- Do not execute Web API writes until this plan is explicitly approved.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolve_output_dir(raw_output_dir: str) -> Path:
    root = project_root()
    log_root = (root / "log").resolve()
    raw_path = Path(raw_output_dir)
    if raw_path.is_absolute():
        output_dir = raw_path.resolve()
    elif raw_path.parts and raw_path.parts[0].lower() == "log":
        output_dir = (root / raw_path).resolve()
    else:
        output_dir = (log_root / "zotero-library-rebuild" / raw_path).resolve()

    if output_dir == log_root or log_root not in output_dir.parents:
        raise SystemExit(f"Output directory must be under repository log directory: {log_root}")
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a dry-run Zotero collection/tag rebuild plan.")
    parser.add_argument(
        "--output-dir",
        default="log/zotero-library-rebuild/dry-run",
        help="Directory for plan artifacts. Use a path under the repository log/ directory.",
    )
    parser.add_argument("--profile", default=None, help="Zotero config profile.")
    parser.add_argument("--library-id", type=int, default=1, help="Local SQLite libraryID. User library is 1.")
    parser.add_argument("--data-dir", default=None, help="Override Zotero data directory containing zotero.sqlite.")
    parser.add_argument("--limit", type=int, default=None, help="Limit scanned parent items for smoke tests.")
    parser.add_argument("--archive-date", default=date.today().isoformat(), help="Archive date suffix.")
    parser.add_argument("--title-sample-size", type=int, default=200, help="Title samples per collection for AI review.")
    args = parser.parse_args()

    cfg = load_config(profile=args.profile)
    data_dir = Path(args.data_dir) if args.data_dir else get_data_dir(cfg)
    db_path = data_dir / "zotero.sqlite"
    if not db_path.exists():
        raise SystemExit(f"Zotero database not found: {db_path}")

    output_dir = resolve_output_dir(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stages = stage_dirs(output_dir)

    archive_root = f"90_ARCHIVE/00_PRE_REBUILD_{args.archive_date}"
    archive_uncertain_path = f"{archive_root}/00_UNSURE_MANUAL_REVIEW"

    with connect_readonly(db_path) as conn:
        collections = collection_rows(conn, args.library_id)
        items = item_rows(conn, args.library_id, args.limit)
        active_items = [item for item in items if not item.is_deleted]
        total_parent_items = count_parent_items(conn, args.library_id)
        tags_before = tag_counts(conn, args.library_id)
        stats = {
            "collection_count": len(collections),
            "scanned_parent_item_count": len(items),
            "scanned_active_parent_item_count": len(active_items),
            "scanned_deleted_parent_item_count": len(items) - len(active_items),
            "total_parent_item_count": total_parent_items,
            "scan_limit": args.limit,
            "tag_count": len(tags_before),
            "library_id": args.library_id,
            "db_path": str(db_path),
        }

    movement_rows: list[dict[str, Any]] = []
    tag_rows: list[dict[str, Any]] = []
    low_confidence_lines = ["# Low Confidence Items", ""]
    for item in active_items:
        targets, proposed_tags, reasons, confidence, signals = classify_item(item, archive_uncertain_path)
        movement_rows.append(
            {
                "phase": "dry_run_classification",
                "item_key": item.item_key,
                "title": item.title,
                "from_collections": item.collection_paths,
                "to_collections": targets,
                "reason": reasons,
                "confidence": confidence,
                "needs_user_confirm": confidence != "high",
            }
        )
        add_tags = [tag for tag in proposed_tags if tag not in item.tags]
        tag_rows.append(
            {
                "item_key": item.item_key,
                "title": item.title,
                "current_tags": item.tags,
                "proposed_add_tags": add_tags,
                "proposed_remove_tags": [],
                "reason": reasons + signals,
                "confidence": confidence,
                "needs_user_confirm": confidence != "high",
            }
        )
        if confidence == "low":
            low_confidence_lines.append(f"- `{item.item_key}` {item.title}")

    collection_profiles = build_collection_profiles(active_items, title_sample_size=args.title_sample_size)
    collection_title_sets = build_collection_title_sets(active_items)
    trash_candidates = build_trash_delete_candidates(items)

    export_dir = stages["00_export_current_state"]
    extract_dir = stages["10_extract_library_signals"]
    ai_dir = stages["20_ai_keyword_tag_review"]
    design_dir = stages["30_design_adjustment"]
    plan_dir = stages["40_plan_for_confirmation"]
    execution_dir = stages["50_execution_results"]

    write_json(export_dir / "collection_tree_before.json", [asdict(coll) for coll in collections])
    write_json(export_dir / "library_stats_before.json", stats)
    write_json(export_dir / "tags_before.json", tags_before)
    write_jsonl(export_dir / "items_before.jsonl", [asdict(item) for item in items])
    write_jsonl(export_dir / "item_collection_edges.jsonl", item_collection_edges(items))
    write_jsonl(export_dir / "item_tag_edges.jsonl", item_tag_edges(items))

    write_json(extract_dir / "collection_profiles.json", collection_profiles)
    write_json(extract_dir / "collection_title_sets.json", collection_title_sets)
    write_jsonl(extract_dir / "trash_delete_candidates.jsonl", trash_candidates)
    write_signal_summary(extract_dir / "signal_summary.md", collection_profiles, len(trash_candidates))

    write_ai_prompt_files(ai_dir)

    write_json(design_dir / "target_collection_tree.json", target_tree_rows())
    write_json(design_dir / "target_collection_create_plan.json", target_collection_create_plan(collections))
    (design_dir / "design_adjustment_notes.md").write_text(
        "# Design Adjustment Notes\n\n"
        "Review `../20_ai_keyword_tag_review/*_prompt.md` results before changing bundled references.\n"
        "If the AI proposes useful changes, update `skill/zotero-library-rebuild/references/collection-design.md`, "
        "`skill/zotero-library-rebuild/references/tag-taxonomy.md`, and the planner keyword rules before execution.\n",
        encoding="utf-8",
    )

    write_json(plan_dir / "archive_collection_plan.json", archive_plan(collections, archive_root))
    write_jsonl(plan_dir / "archive_item_membership_plan.jsonl", archive_item_membership_rows(active_items, archive_root))
    write_jsonl(plan_dir / "item_movement_plan.jsonl", movement_rows)
    write_jsonl(plan_dir / "tag_update_plan.jsonl", tag_rows)
    (plan_dir / "low_confidence_items.md").write_text("\n".join(low_confidence_lines) + "\n", encoding="utf-8")
    write_movement_summary(plan_dir / "movement_summary.md", movement_rows)
    write_tag_summary(plan_dir / "tag_summary.md", tag_rows)
    (plan_dir / "plan_review.md").write_text(
        "# Zotero Rebuild Plan For Confirmation\n\n"
        f"- Archive root: `{archive_root}`\n"
        f"- Uncertain item target: `{archive_uncertain_path}`\n"
        f"- Items scanned: {len(items)}\n"
        f"- Trash delete candidates: {len(trash_candidates)}\n"
        f"- Movement rows: {len(movement_rows)}\n"
        f"- Tag update rows: {len(tag_rows)}\n\n"
        "Confirm this plan before any Zotero Web API writes. Permanent deletion of trash candidates requires a separate explicit approval.\n",
        encoding="utf-8",
    )

    (execution_dir / "execution_placeholder.md").write_text(
        "# Execution Results\n\n"
        "No live Zotero writes were executed by this planner. Populate this directory only after user-confirmed apply phases.\n",
        encoding="utf-8",
    )

    write_summary(
        output_dir / "summary.md",
        db_path=db_path,
        output_dir=output_dir,
        items=items,
        movement_rows=movement_rows,
        tag_rows=tag_rows,
        collections=collections,
    )
    write_plan_md(
        output_dir / "plan.md",
        db_path=db_path,
        output_dir=output_dir,
        archive_root=archive_root,
        archive_uncertain_path=archive_uncertain_path,
        items=items,
        movement_rows=movement_rows,
        tag_rows=tag_rows,
        trash_candidate_count=len(trash_candidates),
    )

    print(json.dumps({"ok": True, "output_dir": str(output_dir), **stats}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

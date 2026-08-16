## 通用执行规则

本文件中的 Zotero workflow 默认通过对应 `tools\*.ps1` wrapper 重新打开一个新的 PowerShell 窗口运行。wrapper 会在新窗口中输出阶段进度，写入运行目录中的 `run.log` 和 `progress.jsonl`；不要再依赖额外的 watch 命令作为主进度来源。

以下规则也已分别内嵌到每个“推荐给代理的直接提示词”中，避免单独复制某一节时遗漏执行约束。

推荐操作顺序：
1. 在仓库根目录运行对应 wrapper，让它打开新的 PowerShell 窗口。
2. 保留新窗口，进度以新窗口中的 wrapper 输出和 `run.log` / `progress.jsonl` 为主。
3. 必要时再检查 `log\...`、`summary.json`、`import_summary.json`、batch 日志或 Web API postcheck 文件。
4. 汇报进度必须基于 wrapper 输出、`run.log`、`progress.jsonl` 或实际产物变化；不要只说“已开始”。
5. 所有 stdout/stderr 和中间日志都放在对应 `log\...` 运行目录；不要散落在仓库根目录、`tools\`、`tmp\` 或临时 `.workspace\...` 中。
6. 仅限调试/CI 时使用 `-RunInCurrentWindow` 在当前 PowerShell 中运行实际流程。

## Clean-up all metadata

### 推荐给代理的直接提示词
```text
执行与日志规则：
- 默认通过对应 wrapper 重新打开新的 PowerShell 7/pwsh 窗口运行；除非调试或 CI，不要追加 `-RunInCurrentWindow`。
- 保留新窗口，进度以新窗口输出和运行目录中的 `run.log`、`progress.jsonl` 为主；不要把额外 watch 命令当作主进度来源。
- 汇报进度必须基于 wrapper 输出、`run.log`、`progress.jsonl` 或实际产物变化，不要只说“已开始”。
- 所有 stdout/stderr、中间文件和诊断日志都必须放在各自 `log\...` 运行目录；不要散落到仓库根目录、`tools\`、`tmp\` 或临时 `.workspace\...` 中。

使用 skill zotero-cli-agent。
在 F:\ChengL1u\10_资源库\代码\zotero-cli-agent 下执行 metadata cleanup。先建立本次运行目录：log\metadata-cleanup-YYYYMMDD-HHMM。
本指令独立包含运行文件规则：metadata-export、cleaned jsonl、dry-run/apply 输出、batch 文件、续跑文件和诊断记录都只放在本次 log\metadata-cleanup-YYYYMMDD-HHMM 目录；不要放在仓库根目录散文件、tmp\ 或临时 .workspace\... 运行目录中。失败、中断、等待确认或需要排查时保留该目录；复核无误后删除本次目录，如果 log\ 已空也删除 log\。

如果在本仓库内单独执行 metadata cleanup，先读取 Zotero 条目 metadata。默认导出命令必须同时跳过已清理 tag 和 20_ARCHIVE 全部 holding collections：
uv run zot --json --detail full summarize-all --exclude-tag workflow/metadata --exclude-tag update/metadata --exclude-collection-key RHBNIDLJ --exclude-collection-key 4W3JSHVT --exclude-collection-key JDL5AMLK --exclude-collection-key AC9IN8II --exclude-collection-key X8KH35G2 --exclude-collection-key 9J9BWP2K --exclude-collection-key LPVR4N2G --limit 5000 > log\metadata-cleanup-YYYYMMDD-HHMM\metadata-export.json

默认排除集合：
- `20_ARCHIVE` (`RHBNIDLJ`) 及其子集合：归档/holding collections，不做日常 metadata cleanup。
- 当前归档子集合 key：`4W3JSHVT` (`200_Zn`), `JDL5AMLK` (`2000_Zn_Inbox`), `AC9IN8II` (`201_Liuqid_Metal`), `X8KH35G2` (`2001_Liquid_Inbox`), `9J9BWP2K` (`202_Cellulose`), `LPVR4N2G` (`2002_Cellulose_Inbox`)。
- `50_WORKSPACE` (`AFTJQCQA`) 默认不排除；只有明确不需要清理 workspace 条目时，才额外追加 `--exclude-collection-key AFTJQCQA`，或在总控 wrapper 中使用 `-ExcludeWorkspaceMetadata`。

导出后检查 metadata-export.json 的 meta：
- `excluded_tags` 应包含 `workflow/metadata` 和 `update/metadata`。
- `excluded_collection_keys` 应默认包含 `RHBNIDLJ`, `4W3JSHVT`, `JDL5AMLK`, `AC9IN8II`, `X8KH35G2`, `9J9BWP2K`, `LPVR4N2G`。
- `count` 是本次需要交给代理判断的条目数；不要对已排除集合生成 cleaned-metadata.jsonl。

只清洗这些字段的格式问题：title、abstractNote、publicationTitle、journalAbbreviation、language、publisher。
清洗目标：去掉 HTML 标签，修复异常空格、断裂换行、特殊符号粘连；保持原意，不改事实内容。
边界处理：化学式、化学计量数和电荷不要插入空格，例如 CO2、H2O、MnO2、Zn2+、LiFePO4、Ni3S2；不要把小数改成 `1. 0`；不要把 `single- versus`、`regio- and` 这类并列短语合并成一个词。
不要修改 DOI、url、date、pages、ISSN、extra.extra、creators、tags、notes。
只输出实际发生变更的条目，生成 log\metadata-cleanup-YYYYMMDD-HHMM\cleaned-metadata.jsonl。

先执行 `uv run zot --json update --from-jsonl log\metadata-cleanup-YYYYMMDD-HHMM\cleaned-metadata.jsonl --dry-run > log\metadata-cleanup-YYYYMMDD-HHMM\metadata-cleanup-dry-run.json`，不要正式写入，等我确认。等待确认期间保留本次 log 目录。

我确认后，按批次正式写入。推荐批大小为 50；如果网络不稳定可降到 25，不要超过 100。每批文件命名为：
- log\metadata-cleanup-YYYYMMDD-HHMM\cleaned-metadata-batch-001.jsonl
- log\metadata-cleanup-YYYYMMDD-HHMM\metadata-cleanup-apply-batch-001.json
- log\metadata-cleanup-YYYYMMDD-HHMM\metadata-cleanup-apply-batch-001.err.log

正式写入命令：
uv run zot --json update --from-jsonl log\metadata-cleanup-YYYYMMDD-HHMM\cleaned-metadata-batch-001.jsonl --add-tag workflow/metadata > log\metadata-cleanup-YYYYMMDD-HHMM\metadata-cleanup-apply-batch-001.json 2> log\metadata-cleanup-YYYYMMDD-HHMM\metadata-cleanup-apply-batch-001.err.log

不要静默等待长批次。`zot update --from-jsonl` 会在 stderr 输出结构化 progress；代理必须实时读取 stderr 或使用总控 wrapper，把进度转成类似：
`[batch 3/13] item 41/50 | overall 141/630 | succeeded=... failed=...`
每批结束后立即报告成功数、失败数、剩余批次数和日志路径。

增量/续跑规则：
- 已成功的 batch 判定标准是 apply JSON 中 `ok=true` 且 `failed=[]`，并且 succeeded 数等于该 batch 行数。
- 中断、超时或 API 断连后，不要重跑全量 cleaned-metadata.jsonl。
- 先读取已有 `metadata-cleanup-apply-batch-*.json`；成功 batch 跳过。
- partial batch 只收集 `data.failed` 中的条目，写入 `cleaned-metadata-retry-failed-001.jsonl` 后单独重试。
- 空文件、缺失输出或 JSON 解析失败的 batch 才重跑该 batch。
全部批次完成后，生成或检查最终汇总：
- 单独流程：人工汇总每个 batch 的 succeeded/failed，确认 cleaned-metadata.jsonl 中所有 key 都成功。

复核无误后删除本次 log\metadata-cleanup-YYYYMMDD-HHMM 目录；如果 log\ 已空，也删除 log\。
```

## Daily 002_Stage Review

### 推荐给代理的直接提示词
```text
使用 skill zotero-cli-agent。
在 F:\ChengL1u\10_资源库\代码\zotero-cli-agent 下处理 Zotero 的 `00_INBOX/002_Stage` 日常审阅与归档分流。这个流程先只读审阅，再给出分类候选；我确认后，才把确认的条目从 `002_Stage` 移动到 `20_ARCHIVE` 下的专题 inbox。

总体安全边界：
- 审阅和分类候选阶段只读，不写 Zotero，不改 zotero.sqlite，不生成 cleaned-metadata/update/delete 文件。默认直接在回复中返回结果；除非我明确要求保存快照，不要把结果散落到仓库根目录、tools\、tmp\ 或临时 .workspace\... 中。
- 写入阶段只在我确认后执行；写入只通过 Zotero Web API 或 `zot collection move` 这类 Web API 写命令完成，永远不要直接写 `zotero.sqlite`。
- 不要把条目移入 Zotero trash，除非我明确说“移入回收站/删除 Zotero 条目”。我在这个流程里说“删除”时，默认含义是从 `002_Stage` 移除源集合归属。

阶段 0：确认集合 key
1. 先运行 `uv run zot --json collection list`，从当前 live collection tree 中确认源集合和目标集合名称/key。不要直接复用旧 key。
2. 当前常用映射仅作核对提示：源集合 `00_INBOX/002_Stage` = `CECXU7YE`；`20_ARCHIVE/200_Zn/2000_Zn_Inbox` = `JDL5AMLK`；`20_ARCHIVE/201_Liuqid_Metal/2001_Liquid_Inbox` = `X8KH35G2`；`20_ARCHIVE/202_Cellulose/2002_Cellulose_Inbox` = `LPVR4N2G`。

阶段 1：返回 002_Stage 审阅表
1. 运行 `uv run zot --json collection items <STAGE_COLLECTION_KEY>` 读取当前集合条目，记录本次总数和当前批次范围。如果刚执行过 Web API 写入且本地 Zotero 还没有同步，则优先用 Zotero Web API 分页读取 `002_Stage` 的远程当前条目。
2. 按 Zotero 当前返回顺序从 1 开始编号。第一批返回 1-100；我说“下一批”时返回 101-200，依此类推。
3. 每条只返回四列，固定表头必须写成：`序号 / key / 中文标题 / 期刊`。
4. 推荐用 Markdown 表格返回，表头固定为：`| 序号 | key | 中文标题 | 期刊 |`。
5. 期刊字段优先取 `extra.publicationTitle`，没有时再取 `extra.journalAbbreviation`，再没有时取 `extra.publisher`；期刊名保持 Zotero 原文，不强行翻译。
6. 标题翻译成中文时保留专有名词、缩写、模型名、材料名和化学式的准确性，例如 MnO2、Zn2+、CO2、LiFePO4、LLM、RAG、VSR、MXene 不要拆坏或过度意译。
7. 返回前说明：`第一批：1-100 / 共 N 条` 或 `第 X 批：A-B / 共 N 条`。

可用的字段抽取命令示例：
$env:PYTHONIOENCODING='utf-8'
$j = uv run zot --json collection items <STAGE_COLLECTION_KEY> | ConvertFrom-Json
$offset = 0
$limit = 100
$i = $offset
$j.data | Select-Object -Skip $offset -First $limit | ForEach-Object {
  $i++
  $journal = ''
  if ($_.extra -and $_.extra.publicationTitle) { $journal = $_.extra.publicationTitle }
  elseif ($_.extra -and $_.extra.journalAbbreviation) { $journal = $_.extra.journalAbbreviation }
  elseif ($_.extra -and $_.extra.publisher) { $journal = $_.extra.publisher }
  [pscustomobject]@{ n=$i; key=$_.key; title=$_.title; journal=$journal }
} | ConvertTo-Json -Depth 8

如果我后续要根据序号删除、移动、保留或分类条目，必须把本次审阅输出对应的 number-to-key 映射视为唯一依据。不要在集合变化后重新读取并套用旧序号；执行任何写操作前先复述将要处理的序号、key 和目标集合，等我确认。

阶段 2：给出归档分流候选
1. 在同一批次或完整 `002_Stage` 条目上筛选 `20_ARCHIVE` 专题 inbox 候选。分类可以交叉；同一条目可以进入多个目标集合。
2. 分类目标：
   - Zn 负极相关：移动到 `2000_Zn_Inbox`。优先匹配明确的 Zn/zinc anode、Zn metal anode、Zn metal battery、Zn deposition/electrodeposition、Zn dendrite/corrosion/HER/side reaction/plating/stripping/interphase/SEI/desolvation/protective layer/current collector 等。普通 Zn-ion cathode 或只泛泛说水系锌电池的不算，除非摘要明确涉及 Zn 负极/沉积/界面失效。
   - 液态金属相关：移动到 `2001_Liquid_Inbox`。匹配 liquid metal、liquid alloy、liquid metal batteries、molten metal/alloy、Na-K liquid alloy、EGaIn、Galinstan、gallium-based liquid metal 等。普通 liquid electrolyte、bulk liquids、liquid water、liquid-solid phase coexistence 不算。
   - 纤维素相关：移动到 `2002_Cellulose_Inbox`。匹配 cellulose、nanocellulose、bacterial cellulose、carboxymethyl cellulose、CMC/CMC-Na、lignocellulosic、cellulosic 等。
3. 确认前输出格式：
   - 先说明 `002_Stage` 当前总数、已审阅范围和候选唯一条目数。
   - 按目标集合分组列出候选，表头固定为：`分类 / 目标集合 / 序号 / key / 中文标题 / 期刊 / 判断`。
   - 如果有交叉分类，单独列出“交叉项”，说明同一 key 将进入哪些目标集合。
   - 对弱匹配或边界项单独列出“暂不建议移动的边界项”，说明不建议移动的原因。
   - 最后明确写出“确认后将移动 N 个唯一条目，并从 002_Stage 移除这些条目的源集合归属”。

阶段 3：确认后执行移动
1. 只处理我确认的序号/key 和目标集合，不要重新筛选后扩大范围。
2. 单目标条目可用 `uv run zot --json collection move <ITEM_KEY> <TARGET_COLLECTION_KEY> --from <STAGE_COLLECTION_KEY>`。
3. 交叉分类条目要确保最终 `collections` 同时包含所有确认的目标集合且不再包含 `002_Stage`。可以通过 Zotero Web API 一次性更新完整 `collections` 列表；如果用 CLI 分步执行，先移入一个目标并移除源集合，再追加其他目标集合，最后必须逐项 Web API 验证。
4. 写入后必须用 Web API 逐项验证：目标集合包含该 key，源集合不再包含该 key。不要用本地 `zot collection items` 作为刚写完后的最终真相。
5. 执行后汇报每个 key 的动作和 Web API 验证结果：`failed=0`、`verification_failed=0` 或列出失败原因。
```

## Full Library Collection Membership Audit

### 推荐给代理的直接提示词
```text
使用 skill zotero-cli-agent。
在 F:\ChengL1u\10_资源库\代码\zotero-cli-agent 下执行 Zotero 全库集合成员关系审计与修复。

目标：理清全库父条目的集合归属，只修复普通集合成员关系，不删除条目，不改 metadata、tags、notes、attachments，不直接写 zotero.sqlite。

固定规则：
- `00_INBOX` 及其所有子集合是入口/暂存区。条目如果已经属于任何更高优先级集合，就不应该继续挂在 `00_INBOX` 或其子集合中。
- `20_ARCHIVE` 及其所有子集合是归档/holding 区。条目如果已经属于 `30_PROJECT`、`40_TOPIC`、`50_WORKSPACE`、`60_CHARACTERIZATION` 中任一根集合或其子集合，就不应该继续挂在 `20_ARCHIVE` 或其子集合中。
- `我的出版物` 是 Zotero 的特殊 My Publications 状态，不是普通 collection。不要查找、创建或移动到名为“我的出版物”的普通集合；只通过 Zotero Web API 的 publications endpoint 或本地 `publicationsItems` 识别。
- `我的出版物` 中的条目只能保留普通集合 `30_PROJECT`、`40_TOPIC`、`50_WORKSPACE`、`60_CHARACTERIZATION` 及其子集合；如果还挂在 `00_INBOX`、`20_ARCHIVE` 或其他普通集合，要移除这些普通集合归属，但保留 My Publications 状态。
- 普通集合优先级：`我的出版物` > `30_PROJECT = 40_TOPIC = 50_WORKSPACE = 60_CHARACTERIZATION` > `20_ARCHIVE` > `00_INBOX`。如果 live tree 中未来出现独立 `10_*` staging 根集合，先报告 key，并按最低优先级处理，除非我重新定义。

执行顺序：
1. 先检查是否有正在运行的 Zotero 写入/导入/清理进程；如果有可能同时改集合成员，先报告，不要并发写入。
2. 建立本次运行目录：`log\collection-membership-audit-YYYYMMDD-HHMMSS`。所有审计、计划、apply、verify、postcheck 文件都放在这个目录；不要散落到仓库根目录、tools\、tmp\ 或临时 .workspace\... 中。
3. 通过 live Zotero Web API 或 `uv run zot --json collection list` 读取当前 collection tree，重新解析 root key 和完整 path。不要复用旧 key。
4. 当前常见 root key 仅作核对提示，不能直接当作真值：`00_INBOX=AG7NQ5UW`，`20_ARCHIVE=RHBNIDLJ`，`30_PROJECT=VU3HIBI2`，`40_TOPIC=FAPUW5I2`，`50_WORKSPACE=AFTJQCQA`，`60_CHARACTERIZATION=E6NFXC2N`。
5. 用 Zotero Web API 分页读取全库 top-level parent items，并读取 My Publications 列表。不要用附件、note、annotation 参与集合冲突判断。
6. 生成只读审计产物：
   - `summary.json`
   - `collections.json`
   - `all-top-items.json`
   - `repair-plan.json`
   - `repair-plan.jsonl`
   - `manual-review.json`
   - `unchanged-conflicts.json`
7. 如果出现未知 root、live tree 缺少预期根集合、`manual-review.json` 非空，先停止并把人工复核项返回给我，不要猜测写入。
8. 如果冲突都能按固定优先级自动判定，则只更新每个父条目的 `data.collections` 列表：移除低优先级集合 key，保留高优先级集合 key。不要删除 Zotero 条目，不要移入 trash，不要改 My Publications 状态。
9. 写入前逐条重新读取 live item。如果 live `collections` 与审计时的 `current_collections` 不一致，标记 `skipped_live_drift` 并跳过该条，避免覆盖我或 Zotero 同步刚产生的新变化。
10. 写入只能通过 Zotero Web API / pyzotero `update_item` 完成；永远不要直接写 `zotero.sqlite`。
11. 每条写入后立即 Web API 读回验证：`live_after_collections` 必须与计划中的 `new_collections` 一致。把结果写入 `apply-results.json`。
12. 全部写入后重新跑一次全库 postcheck，生成：
   - `postcheck-summary.json`
   - `postcheck-remaining-plan.json`
   只有 `remaining_planned_update_count=0` 且 `remaining_manual_review_count=0` 才算完成。

汇报格式：
- 说明本次读取的 top-level parent item 数、My Publications 数、计划更新数、已更新数、跳过 live drift 数、验证失败数、postcheck 剩余冲突数。
- 给出本次 log 目录和关键文件路径。
- 提醒 Zotero Web API 写入后需要 Zotero 桌面同步，本地 SQLite/界面才会完全反映。

边界：
- `30_PROJECT`、`40_TOPIC`、`50_WORKSPACE`、`60_CHARACTERIZATION` 同级，可以并存，不互相排斥。
- `20_ARCHIVE` 内不同子集合之间的交叉归属不在本流程自动裁决，除非它同时冲突于更高优先级根集合。
- 没有普通集合的 My Publications 条目可以保持无普通 collection；不要为了规则强行塞进 `30/40/50/60`。
```

## Workspace RAG Incremental Index

### 推荐给代理的直接提示词
```text
当前日常目标是 F:\ChengL1u\10_资源库\代码\zotero-cli-agent\.workspace\501-mno2-zn，
对应 Zotero 集合 501-MnO2-Zn 及其子集合。full-library-rag 已删除，脚本默认 workspace 名已改为 rag-workspace。

集合 key：
KRI7W5QZ,8FAPWVJM,8J9NPUPR,PD6IDJ2R,PUR627E3,R7VCZW46,S67ZHINI,WR5PK9MT,XIWCAHQT,ZF6UGG6U

安全边界：
- 只通过 tools\run-rag-workspace.ps1 更新 workspace/index/embedding。
- 不直接写 rag.idx.sqlite，不直接写 zotero.sqlite，不写 Zotero Web API。
- .workspace\501-mno2-zn 是持久 RAG workspace，保留。
- .zot\state\pdf_cache.sqlite 是 MinerU/PDF 抽取共享缓存，保留；删除它只会导致以后重抽 PDF。
- log\rag-workspace-* 和 log\rag-evidence-search-* 是运行日志；确认不需要复盘后可以删除。

先 dry-run 看是否有新增或缺口：
$collections = 'KRI7W5QZ,8FAPWVJM,8J9NPUPR,PD6IDJ2R,PUR627E3,R7VCZW46,S67ZHINI,WR5PK9MT,XIWCAHQT,ZF6UGG6U'
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-workspace.ps1 `
  -WorkspaceName 501-mno2-zn `
  -Collections $collections `
  -DryRun `
  -KeepLog `
  -RunInCurrentWindow

正式增量更新。默认新窗口运行，进度看新窗口和 log\rag-workspace-*\logs\index.log / embed.log：
$collections = 'KRI7W5QZ,8FAPWVJM,8J9NPUPR,PD6IDJ2R,PUR627E3,R7VCZW46,S67ZHINI,WR5PK9MT,XIWCAHQT,ZF6UGG6U'
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-workspace.ps1 `
  -WorkspaceName 501-mno2-zn `
  -Collections $collections `
  -KeepLog

只补 embedding，不重新 PDF 抽取或 item index：
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-workspace.ps1 `
  -WorkspaceName 501-mno2-zn `
  -EmbedOnly `
  -KeepLog

完成后复核计数（chunks 在 SQLite，向量在 Qdrant local）：
@'
import sqlite3
from pathlib import Path
from zotero_cli_agent.config import load_vector_store_config
from zotero_cli_agent.core.semantic_search import QdrantVectorStore, resolve_vector_store_path

p = Path(".workspace/501-mno2-zn/rag.idx.sqlite")
con = sqlite3.connect(p)
cur = con.cursor()
items = cur.execute("select count(distinct item_key) from chunks").fetchone()[0]
chunks = cur.execute("select count(*) from chunks").fetchone()[0]
con.close()

vs = QdrantVectorStore(resolve_vector_store_path(load_vector_store_config()), "ws_501-mno2-zn")
with_embedding = vs.count()
vs.close()

print("items", items)
print("chunks", chunks)
print("with_embedding", with_embedding)
print("missing_embedding", max(chunks - with_embedding, 0))
'@ | uv run python -

> 语义搜索已切换为 SQLite FTS5 + Qdrant local：向量不再存于 rag.idx.sqlite 的 embedding 列。
> 旧索引需要重建一次：`zot workspace index 501-mno2-zn --force`，再 `zot workspace embed 501-mno2-zn` 写入 Qdrant。

查证据。BM25 和 embedding 已完成时默认用 auto，也就是 hybrid；rerank 是查询时在线精排，不是离线构建步骤：
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-evidence-search.ps1 `
  -WorkspaceName 501-mno2-zn `
  -Question "MnO2 zinc battery failure degradation mechanism Mn dissolution structural collapse capacity fading electrolyte evidence" `
  -Mode auto `
  -TopK 8 `
  -RerankTopN 50 `
  -KeepLog `
  -RunInCurrentWindow

如果 rerank provider 异常，先加 -NoRerank 退回 hybrid 原始排序；如果只看正文或补充信息，加 -PdfKind main 或 -PdfKind supplementary。

清理中间文件：
- 可以删除 log\rag-workspace-* 和 log\rag-evidence-search-*。
- 不删除 .workspace\501-mno2-zn。
- 不删除 .zot\state\pdf_cache.sqlite。
- 不删除 .workspace\_qdrant（本地 Qdrant 向量库）。
```

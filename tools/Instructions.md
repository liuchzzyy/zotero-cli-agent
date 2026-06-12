## 通用执行规则

本文件中的 Zotero workflow 默认通过对应 `tools\*.ps1` wrapper 重新打开一个新的 PowerShell 窗口运行。wrapper 会在新窗口中输出阶段进度，写入运行目录中的 `run.log` 和 `progress.jsonl`；不要再依赖额外的 watch 命令作为主进度来源。

以下规则也已分别内嵌到每个“推荐给代理的直接提示词”中，避免单独复制某一节时遗漏执行约束。

推荐操作顺序：
1. 在仓库根目录运行对应 wrapper，让它打开新的 PowerShell 窗口。
2. 保留新窗口，进度以新窗口中的 wrapper 输出和 `run.log` / `progress.jsonl` 为主。
3. 必要时再检查 `log\...`、`summary.json`、`import_summary.json`、batch 日志或 Web API postcheck 文件。
4. 汇报进度必须基于 wrapper 输出、`run.log`、`progress.jsonl` 或实际产物变化；不要只说“已开始”。
5. 所有 stdout/stderr 和中间日志都放在对应 `log\...` 运行目录；不要散落在仓库根目录、`tools\`、`src\zotero_cli_workflows\`、`tmp\` 或临时 `.workspace\...` 中。
6. 仅限调试/CI 时使用 `-RunInCurrentWindow` 在当前 PowerShell 中运行实际流程。

## Clean-up all metadata

### 推荐给代理的直接提示词
```text
执行与日志规则：
- 默认通过对应 wrapper 重新打开新的 PowerShell 7/pwsh 窗口运行；除非调试或 CI，不要追加 `-RunInCurrentWindow`。
- 保留新窗口，进度以新窗口输出和运行目录中的 `run.log`、`progress.jsonl` 为主；不要把额外 watch 命令当作主进度来源。
- 汇报进度必须基于 wrapper 输出、`run.log`、`progress.jsonl` 或实际产物变化，不要只说“已开始”。
- 所有 stdout/stderr、中间文件和诊断日志都必须放在各自 `log\...` 运行目录；不要散落到仓库根目录、`tools\`、`src\zotero_cli_workflows\`、`tmp\` 或临时 `.workspace\...` 中。

使用 skill zotero-cli-agent。
在 E:\Desktop\CodingDaily\zotero-cli-agent 下执行 metadata cleanup。先建立本次运行目录：log\metadata-cleanup-YYYYMMDD-HHMM。
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

## Daily RSS DOI Import

### 推荐给代理的直接提示词
```text
执行与日志规则：
- 默认通过对应 wrapper 重新打开新的 PowerShell 窗口运行；除非调试或 CI，不要追加 `-RunInCurrentWindow`。
- 保留新窗口，进度以新窗口输出和运行目录中的 `run.log`、`progress.jsonl` 为主；不要把额外 watch 命令当作主进度来源。
- 汇报进度必须基于 wrapper 输出、`run.log`、`progress.jsonl` 或实际产物变化，不要只说“已开始”。
- 所有 stdout/stderr、中间文件和诊断日志都必须放在各自 `log\...` 运行目录；不要散落到仓库根目录、`tools\`、`src\zotero_cli_workflows\`、`tmp\` 或临时 `.workspace\...` 中。

在 E:\Desktop\CodingDaily\zotero-cli-agent 下执行 Daily RSS Item Import。

默认目标集合按条目类型二选一：普通条目放入 `00_INBOX/000_Inbox`；带 `tracked_author:*` 的作者提醒条目只放入 `00_INBOX/001_Author/<作者名>`，不要同时放入根 `00_INBOX` 或 `00_INBOX/000_Inbox`。不要自动放入 `002_Stage`、`003_Cleaned` 或其他子集合。

本指令独立包含运行文件规则：import_list、checkpoint、summary、failed_results、progress 和恢复审计文件都放在 log\rss-daily-item-import_YYYY-MM-DD；不要放在仓库根目录散文件、tmp\ 或临时 .workspace\... 运行目录中。成功且 failed=0 时默认清理本次 log 目录；失败、中断或需要恢复时保留该目录。

日常运行不要手动拆开清洗/导入步骤，直接调用 wrapper。默认调用会重新打开一个新的 PowerShell 窗口，实际 import 在新窗口中运行；wrapper 把本次 import_list、checkpoint、summary、failed_results、`run.log`、`progress.jsonl` 等运行文件放到 log\rss-daily-item-import_YYYY-MM-DD，并在 failed=0 成功完成后自动删除本次 log 目录：
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-daily-rss-doi-import.ps1 -Date YYYY-MM-DD -ProgressIntervalSeconds 5

推荐直接在 PowerShell 中运行 wrapper，保留新窗口输出；进度以新窗口输出、`run.log`、`progress.jsonl` 和 import_summary.json 为准。只有调试/CI 才追加 `-RunInCurrentWindow`。

默认读取：
E:\Desktop\CodingDaily\rss-cli-agent\storage\exports\YYYY-MM-DD.selected.json

当前 RSS selected JSON 是扁平数组，字段为 `entry_uid/title/doi/time/url/state`；导入器必须使用顶层 `url` 处理无 DOI 条目，并用顶层 `time` 写入 Zotero date。不要再假设存在旧版 `source.link` 或 `source.published_at` 嵌套字段。

GitHub Actions 定时运行：
- workflow: `.github/workflows/daily-rss-zotero-import.yml`
- 定时：北京时间每天 03:10；GitHub cron 使用 UTC，所以配置为 `10 19 * * *`。
- JSON 来源：`https://raw.githubusercontent.com/liuchzzyy/rss-cli-agent/main/storage/exports/YYYY-MM-DD.selected.json`
- 必需 Actions secrets：`ZOT_LIBRARY_ID`、`ZOT_API_KEY`。
- 可选 Actions secrets：`ZOT_CROSSREF_MAILTO`；`RSS_REPO_TOKEN` 仅在 rss-cli-agent 变为私有仓库时需要。
- GitHub runner 没有本地 Zotero SQLite；workflow 必须使用 `-SkipLibraryExport -SkipLocalDb`，让导入阶段只依赖 Zotero Web API。

如果 RSS selected JSON 在非默认位置，必须显式传入完整路径：
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-daily-rss-doi-import.ps1 -Date YYYY-MM-DD -SelectedJson "E:\Desktop\CodingDaily\rss-cli-agent\storage\exports\YYYY-MM-DD.selected.json" -ProgressIntervalSeconds 5

如果需要保留成功运行记录用于审查，加 `-KeepLog`；否则不要保留成功运行的 log 目录。

运行时必须显示实时进度。关注 processed/total、created_new、reused_existing、already_routed、failed。长时间停在 preflight/import starting 时，检查 log\rss-daily-item-import_YYYY-MM-DD\rss_item_import\import_summary.json 和是否仍有 import_rss_build_zotero_items.py 进程，不要凭表面输出判断卡死。
如果 import list summary 显示 new_items=0，wrapper 应直接写出 created_new=0、reused_existing=0、already_routed=0、failed=0 的 summary，并跳过 import-list 子命令；不要为 0 个 RSS item 启动空导入进程。

如果 wrapper 已经完成且 failed=0：
- 本次 log\rss-daily-item-import_YYYY-MM-DD 应该已被自动删除；如果使用过 -KeepLog，复核无误后手动删除。
- 删除旧版本残留的根目录 rss_failed_dois_YYYY-MM-DD.txt（如果存在）。
- 提醒用户 Zotero Web API 写入后需要 Zotero 同步，本地 SQLite 才会完全反映。

如果中途失败或被中断且 log\rss-daily-item-import_YYYY-MM-DD 还在：
- 不要立刻重跑 wrapper；wrapper 会重建本次输出目录，可能丢掉 checkpoint。
- 先确认没有残留 import_rss_build_zotero_items.py 进程。
- 用同一个 import_list 和 output_dir 恢复：
.\.venv\Scripts\python.exe src\zotero_cli_workflows\import_rss_build_zotero_items.py import-list --import-list log\rss-daily-item-import_YYYY-MM-DD\rss_item_import_list\import_list.json --output-dir log\rss-daily-item-import_YYYY-MM-DD\rss_item_import --library user --apply
- 恢复完成后检查 failed_results.json；若为空且 checkpoint 覆盖全部 import_list entries，再删除旧版本残留的根目录 rss_failed_dois_YYYY-MM-DD.txt，并清理本次 log\rss-daily-item-import_YYYY-MM-DD。
- 如果失败来自 metadata/Crossref 解析异常，先修复代码并补测试，再基于原 checkpoint 恢复；不要清空本次 log 目录。
```

## Daily 002_Stage Review

### 推荐给代理的直接提示词
```text
使用 skill zotero-cli-agent。
在 E:\Desktop\CodingDaily\zotero-cli-agent 下处理 Zotero 的 `00_INBOX/002_Stage` 日常审阅与归档分流。这个流程先只读审阅，再给出分类候选；我确认后，才把确认的条目从 `002_Stage` 移动到 `20_ARCHIVE` 下的专题 inbox。

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
在 E:\Desktop\CodingDaily\zotero-cli-agent 下执行 Zotero 全库集合成员关系审计与修复。

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

## Remove Newer DOI Duplicates

### 推荐给代理的直接提示词
```text
执行与日志规则：
- 默认通过对应 wrapper 重新打开新的 PowerShell 窗口运行；除非调试或 CI，不要追加 `-RunInCurrentWindow`。
- 保留新窗口，进度以新窗口输出和运行目录中的 `run.log`、`progress.jsonl` 为主；不要把额外 watch 命令当作主进度来源。
- 汇报进度必须基于 wrapper 输出、`run.log`、`progress.jsonl` 或实际产物变化，不要只说“已开始”。
- 所有 stdout/stderr、中间文件和诊断日志都必须放在各自 `log\...` 运行目录；不要散落到仓库根目录、`tools\`、`src\zotero_cli_workflows\`、`tmp\` 或临时 `.workspace\...` 中。

不要用 title 模糊匹配做去重。
直接在 E:\Desktop\CodingDaily\zotero-cli-agent 下调用 tools\remove-newer-doi-duplicates.ps1。

本指令独立包含运行文件规则：dry-run 输出、apply 输出、计划记录和诊断日志都放在本次 log\remove-newer-doi-duplicates-YYYYMMDD-HHMM 目录；不要放在仓库根目录散文件、tmp\ 或临时 .workspace\... 运行目录中。复核删除结果无误后清理本次目录；失败或等待确认时保留。

规则固定为：只按 DOI 精确判断；同 DOI 时保留 date_added 更早的旧条目，删除 date_added 更晚的新条目。
执行时必须给出实时进度：查询 DOI 重复项、构建 keep/delete 计划、每个重复组的 keep/delete 判断；正式删除时还要报告批次编号、已删除数、失败数、总体百分比。

默认调用会重新打开一个新的 PowerShell 窗口，实际去重在新窗口中运行；wrapper 会在 `log\remove-newer-doi-duplicates-YYYYMMDD-HHMMSS` 写入 `run.log` 和 `progress.jsonl`。只有调试/CI 才追加 `-RunInCurrentWindow`。

先执行默认 dry-run 看 keep/delete 计划；我确认后，再加 -Apply 正式删除。dry-run 和 apply 默认会各自生成一个时间戳运行目录；正式结果以 apply 运行目录为准。
复核删除结果无误后，删除本次 log\remove-newer-doi-duplicates-YYYYMMDD-HHMM 目录；如果失败或等待我确认，保留该目录。
```

## Batch AI Note Analysis

### 推荐给代理的直接提示词
```text
执行与日志规则：
- 默认通过对应 wrapper 重新打开新的 PowerShell 窗口运行；除非调试或 CI，不要追加 `-RunInCurrentWindow`。
- 保留新窗口，进度以新窗口输出和运行目录中的 `run.log`、`progress.jsonl` 为主；不要把额外 watch 命令当作主进度来源。
- 汇报进度必须基于 wrapper 输出、`run.log`、`progress.jsonl` 或实际产物变化，不要只说“已开始”。
- 所有 stdout/stderr、中间文件和诊断日志都必须放在各自 `log\...` 运行目录；不要散落到仓库根目录、`tools\`、`src\zotero_cli_workflows\`、`tmp\` 或临时 `.workspace\...` 中。

使用 E:\Desktop\CodingDaily\zotero-cli-agent\tools\run-ai-note-generation.ps1 批量生成 Zotero AI note，不要手动拼长命令逐条跑。

目标：
对尚未带有 `workflow/ai_note` 或旧 `update/AInote` 的非书籍条目，读取所有本地 PDF 附件，使用 MinerU 抽取 Markdown 和图片，经 CLIProxyAPI 的 gpt-5.5（reasoning effort=`xhigh`）生成“AI条目分析 - <title>”note，写回 Zotero Web API，并给父条目打 tag `workflow/ai_note`。

本指令独立包含运行文件规则：checkpoint、preview、results、failures、notes、MinerU 临时资产和 batch logs 都放在 log\ai-note-analysis-batch-YYYYMMDD-HHMMSS；不要放在仓库根目录散文件、tmp\ 或临时 .workspace\... 运行目录中。完整成功并复核无误后清理本次目录；失败、中断、等待审查或需要保留 MinerU 原始材料时保留。

默认命令。wrapper 默认扫描 `00_INBOX/003_Cleaned` 集合，默认把 checkpoint、preview、results、failures、notes、MinerU 临时资产和 batch logs 放到 log\ai-note-analysis-batch-YYYYMMDD-HHMMSS，并在完整成功后自动清理本次 log 目录：
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-ai-note-generation.ps1 -BatchSize 3
默认会打开新 PowerShell 窗口；调试时才追加 `-RunInCurrentWindow`。

先验证候选条目时用 dry-run；dry-run 成功结束后也会清理本次 log 目录，等待审查时可加 -KeepLog：
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-ai-note-generation.ps1 -DryRun -BatchSize 3 -ScanLimit 100 -KeepLog

只处理指定条目时用：
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-ai-note-generation.ps1 -Keys VH4PXB5G -BatchSize 1

边界和跳过规则：
- 已有 `workflow/ai_note` 或旧 `update/AInote` 的父条目默认完全跳过，不重复生成 note。
- 同一个 output/checkpoint 中已经 tagged 的条目也跳过；这是为了避免 Zotero Web API 写入后，本地 SQLite 尚未同步导致重复处理。
- book 和 bookSection 跳过；当前不做书籍 AI 分析。
- 无 PDF、PDF 路径缺失、PDF 超过 max PDF 大小、MinerU 抽取失败、AI 分类 uncertain、AI 调用失败、Zotero 写入失败，都不打 `workflow/ai_note`，便于下次继续。
- Zotero 读操作来自本地 SQLite；写 note/tag 通过 Zotero Web API。写入成功后需要 Zotero 同步，本地数据库才会看到新 note 和 tag。

模型和图片边界：
- 默认使用 CLIProxyAPI: http://127.0.0.1:8317/v1，模型 gpt-5.5，reasoning effort=`xhigh`，模式 mineru-markdown-images。
- CLIProxyAPI 的 gpt-5.5 已验证可以读取 image_url/base64 图片。
- DeepSeek deepseek-v4-pro 不支持 image_url 图片；如果切到 DeepSeek，只能用 mineru-text，不能使用 mineru-markdown-images。
- 不要把 MinerU Markdown 里的本地图片路径直接当作可读图片；脚本会把 MinerU 输出图片转成 base64 data URL 后发送给支持视觉的模型。
- 默认每个条目最多发送 24 张 MinerU 图片，避免请求过大。必要时可调整 -MaxImages，但不要无上限发送全部图片。

实时进度要求：
- 运行时必须保留终端输出，不要静默后台运行。
- 进度中应能看到扫描、跳过原因、MinerU upload/process/download、classify、analyze、note、tag、done、summary。
- 每批都会写 log\ai-note-analysis-batch-YYYYMMDD-HHMMSS\logs\batch-XXX.log；如果长时间停在 MinerU process 或 AI analyze，先看当前 batch log，不要盲目重启全量。

中间文件和清理：
- 默认输出目录为 log\ai-note-analysis-batch-YYYYMMDD-HHMMSS，不再使用 .workspace\ai-note-analysis-batch-* 作为运行目录。
- 成功批次后脚本会自动删除 mineru-assets 中间目录，避免图片和 MinerU ZIP 解包文件长期占用空间。
- 完整成功后脚本会删除本次 log\ai-note-analysis-batch-YYYYMMDD-HHMMSS；如果 log\ 已空，也删除 log\。
- 如果某批失败，log\ai-note-analysis-batch-YYYYMMDD-HHMMSS 会保留用于诊断，里面包括 notes、results.json、failures.json、summary.json、preview.json、checkpoint.json、logs\batch-*.log。
- 如果需要审查 MinerU 原始 Markdown/图片，加 -NoCleanIntermediate 保留中间文件；这也会保留本次 log 目录。
- 不要删除 checkpoint.json；批量处理中断后继续使用同一个 -OutputDir 才能避免重复处理已写入但本地尚未同步的条目。

失败恢复：
- 如果失败在 MinerU 上传/下载，优先用原 log\ai-note-analysis-batch-YYYYMMDD-HHMMSS 目录重跑；已缓存的 MinerU 资产会被复用，除非加 -RefreshMineruCache。
- 如果失败在 AI 调用，检查 CLIProxyAPI 是否运行、/v1/models 是否可用、模型是否支持图片。
- 如果失败在 Zotero 写入，检查 ZOT_API_KEY / ZOT_LIBRARY_ID 和 Web API 权限，不要写本地 zotero.sqlite。
- 如果某批有 failures，默认停止并保留本次 log 目录；不要立即用 -Force 全量重跑。
```

### 常用参数
```powershell
# 小批量正式运行，推荐默认；成功后自动清理本次 log 目录
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-ai-note-generation.ps1 -BatchSize 3

# 保留 MinerU 中间 Markdown 和图片，便于检查
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-ai-note-generation.ps1 -BatchSize 1 -NoCleanIntermediate

# 复用同一个 log 输出目录继续跑，避免本地 Zotero 未同步时重复
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-ai-note-generation.ps1 -BatchSize 3 -OutputDir log\ai-note-generation-YYYYMMDD-HHMMSS

# 成功后也保留运行目录用于审查
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-ai-note-generation.ps1 -BatchSize 3 -KeepLog

# 切到 DeepSeek 时只能用文本模式，不要使用 mineru-markdown-images
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-ai-note-generation.ps1 -BatchSize 3 -Model deepseek-v4-pro -BaseUrl https://api.deepseek.com -PdfInputMode mineru-text
```

## Update AI Note Citation Keywords

### 推荐给代理的直接提示词
```text
执行与日志规则：
- 默认通过对应 wrapper 重新打开新的 PowerShell 窗口运行；除非调试或 CI，不要追加 `-RunInCurrentWindow`。
- 保留新窗口，进度以新窗口输出和运行目录中的 `run.log`、`progress.jsonl` 为主；不要把额外 watch 命令当作主进度来源。
- 汇报进度必须基于 wrapper 输出、`run.log`、`progress.jsonl` 或实际产物变化，不要只说“已开始”。
- 所有 stdout/stderr、中间文件和诊断日志都必须放在各自 `log\...` 运行目录；不要散落到仓库根目录、`tools\`、`src\zotero_cli_workflows\`、`tmp\` 或临时 `.workspace\...` 中。

使用 E:\Desktop\CodingDaily\zotero-cli-agent\tools\run-citation-key-update-from-ai-notes.ps1 更新已经带有 workflow/ai_note 的父条目 citationKey，不要手动逐条改 Zotero，不要直接写 zotero.sqlite。

目标：
读取本地 Zotero SQLite 中带 workflow/ai_note 的父条目及其 AI note，对比现有 citationKey，生成统一的引用关键词，并通过 Zotero Web API 写回父条目 citationKey；写入成功后给父条目添加 tag workflow/keyword。

本指令独立包含运行文件规则：items、generated、updates、applied、failed_generation、failed_apply、summary、remaining 和 logs 都放在 log\ai-note-keyword-update 或指定的 log\ai-note-keyword-update-YYYYMMDD-HHMM 目录；不要放在仓库根目录散文件、tmp\ 或临时 .workspace\... 运行目录中。失败、中断、等待复核或等待充值时保留本次 log 目录；确认全量完成并复核后才清理。

关键词格式：
领域/体系 | 机制/关键问题 | 性能优势/价值 | 可选先进表征方法 | 可选制备方法 | 可选理论 | 疑问：最大破绽

格式规则：
- 最终 citationKey 是纯文本，不要 Markdown 反引号，不要方括号。
- 前三槽和最后的“疑问：”槽必填；可选先进表征方法、制备方法、理论/模型只有 AI note 中确实有时才追加，没有就不写，不要补空槽。
- 可选槽按“先进表征方法 | 制备方法 | 理论/模型”的语义顺序追加，每类最多一个短槽，可以用逗号合并同类术语。
- 引用关键词必须指出这篇文章最大的破绽、最弱证据、最值得追问的假设或外推风险，不要泛写“无明显破绽”。
- 统一通用术语；例如“液态Na-K合金负极”“Na-K液态合金负极”“液态Na-K合金”“Na-K液态合金”都简写为 Na-K。
- 具体 prompt 不再写死在 Python 中，保存在 tools\templates\citation-key-from-ai-notes-prompt.json；修改格式要求或术语统一时优先改这个 JSON。

推荐 wrapper。默认不写 Zotero，只刷新 status；完整运行需要显式 -FullRun：
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-citation-key-update-from-ai-notes.ps1 -Status
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-citation-key-update-from-ai-notes.ps1 -FullRun
默认会打开新 PowerShell 窗口；调试时才追加 `-RunInCurrentWindow`。

分步运行时用：
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-citation-key-update-from-ai-notes.ps1 -Generate
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-citation-key-update-from-ai-notes.ps1 -RetryFailed
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-citation-key-update-from-ai-notes.ps1 -DryRunApply
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-citation-key-update-from-ai-notes.ps1 -Apply
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-citation-key-update-from-ai-notes.ps1 -Status

当前推荐模型是 deepseek-v4-flash；不要再用 deepseek-v4-pro 做这个关键词流程，pro 在本流程里明显更慢。wrapper 默认 Model=deepseek-v4-flash。如果临时用 Python 子命令，显式指定 flash：
uv run python src\zotero_cli_workflows\update_citation_keys_from_ai_notes.py generate --skip-done-tag --model deepseek-v4-flash

Python 子命令仍可用于调试。默认工作目录是 log\ai-note-keyword-update，不再使用 .workspace\ai-note-keyword-update：
uv run python src\zotero_cli_workflows\update_citation_keys_from_ai_notes.py generate --skip-done-tag --model deepseek-v4-flash
uv run python src\zotero_cli_workflows\update_citation_keys_from_ai_notes.py generate --retry-failed --batch-size 1 --model deepseek-v4-flash
uv run python src\zotero_cli_workflows\update_citation_keys_from_ai_notes.py apply --dry-run
uv run python src\zotero_cli_workflows\update_citation_keys_from_ai_notes.py apply --zotero-timeout 90
uv run python src\zotero_cli_workflows\update_citation_keys_from_ai_notes.py status

如果要临时测试另一版 prompt：
uv run python src\zotero_cli_workflows\update_citation_keys_from_ai_notes.py --prompt-path tools\templates\citation-key-from-ai-notes-prompt.json generate --skip-done-tag --model deepseek-v4-flash
或用 wrapper：
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-citation-key-update-from-ai-notes.ps1 -Generate -PromptPath tools\templates\citation-key-from-ai-notes-prompt.json

中间文件和续跑：
- 默认中间文件保存在 log\ai-note-keyword-update，包括 items.jsonl、generated.jsonl、updates.jsonl、applied.jsonl、failed_generation.jsonl、failed_apply.jsonl、summary.json、remaining.jsonl，以及 logs\*.log。
- 运行时终端和 logs\*.log 会实时输出 progress/progress_label，例如 generate 353/444、apply 81/444；如果长时间不变，再检查当前 log 和模型/API 状态。
- 如果要另开一次独立运行，用 --workspace log\ai-note-keyword-update-YYYYMMDD-HHMM；不要放到 .workspace。
- 续跑时复用同一个 log 目录；脚本会跳过 generated.jsonl、failed_generation.jsonl、applied.jsonl、failed_apply.jsonl 中已经记录且未解决的 key。
- 如果只想补跑生成失败的少数条目，用 wrapper 的 -RetryFailed，或 Python 的 --retry-failed --batch-size 1；不要用 --force 全量重跑。
- 每次 generate/apply/status 都会自动刷新 summary.json 和 remaining.jsonl；先看 summary.json 的 remaining、not_applied、generation_failed_unresolved、apply_failed_unresolved，再决定下一步。generation_failed_history_total 只是历史失败记录数，不代表当前仍失败。
- 如果 remaining.jsonl 只剩少数反复非 JSON 条目，可以读取对应 AI note 后人工整理 citationKey，追加到 generated.jsonl，再运行 apply；不要继续无意义消耗模型调用。
- 如果 DeepSeek 返回 402 Insufficient Balance，脚本会停止且不把待处理条目标记为失败；保留 log\ai-note-keyword-update，充值或切换模型后继续同一个目录。
- 如果本地 Zotero SQLite 尚未同步，优先用 --skip-done-tag 跳过已经打 workflow/keyword 的父条目；不要依赖直接改 zotero.sqlite。

安全边界：
- 读操作来自本地 SQLite；写 citationKey/tag 只通过 Zotero Web API。
- 不直接写 zotero.sqlite，不删除 Zotero 本地库文件。
- 失败、中断、等待复核或等待充值时不要清理 log\ai-note-keyword-update；只有确认全量完成并复核后才清理。
- Web API 写入后需要 Zotero 同步，本地 SQLite 才能看到新 citationKey/tag；抽样验证优先读 Web API。
```

## Full Library RAG Incremental Index

### 推荐给代理的直接提示词
```text
当前日常目标是 F:\ChengL1u\10_Coding\zotero-cli-agent\.workspace\501-mno2-zn，
对应 Zotero 集合 501-MnO2-Zn 及其子集合。full-library-rag 已删除，不要再把它当默认目标。

集合 key：
KRI7W5QZ,8FAPWVJM,8J9NPUPR,PD6IDJ2R,PUR627E3,R7VCZW46,S67ZHINI,WR5PK9MT,XIWCAHQT,ZF6UGG6U

安全边界：
- 只通过 tools\run-rag-full-library.ps1 更新 workspace/index/embedding。
- 不直接写 rag.idx.sqlite，不直接写 zotero.sqlite，不写 Zotero Web API。
- .workspace\501-mno2-zn 是持久 RAG workspace，保留。
- .zot\state\pdf_cache.sqlite 是 MinerU/PDF 抽取共享缓存，保留；删除它只会导致以后重抽 PDF。
- log\rag-full-library-* 和 log\rag-evidence-search-* 是运行日志；确认不需要复盘后可以删除。

先 dry-run 看是否有新增或缺口：
$collections = 'KRI7W5QZ,8FAPWVJM,8J9NPUPR,PD6IDJ2R,PUR627E3,R7VCZW46,S67ZHINI,WR5PK9MT,XIWCAHQT,ZF6UGG6U'
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-full-library.ps1 `
  -WorkspaceName 501-mno2-zn `
  -Collections $collections `
  -DryRun `
  -KeepLog `
  -RunInCurrentWindow

正式增量更新。默认新窗口运行，进度看新窗口和 log\rag-full-library-*\logs\index.log / embed.log：
$collections = 'KRI7W5QZ,8FAPWVJM,8J9NPUPR,PD6IDJ2R,PUR627E3,R7VCZW46,S67ZHINI,WR5PK9MT,XIWCAHQT,ZF6UGG6U'
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-full-library.ps1 `
  -WorkspaceName 501-mno2-zn `
  -Collections $collections `
  -EmbeddingDevice api `
  -KeepLog

只补 embedding，不重新 PDF 抽取或 item index：
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-full-library.ps1 `
  -WorkspaceName 501-mno2-zn `
  -EmbedOnly `
  -EmbeddingDevice api `
  -KeepLog

完成后复核 SQLite 计数：
@'
import sqlite3
from pathlib import Path
p = Path(".workspace/501-mno2-zn/rag.idx.sqlite")
con = sqlite3.connect(p)
cur = con.cursor()
print("items", cur.execute("select count(distinct item_key) from chunks").fetchone()[0])
print("chunks", cur.execute("select count(*) from chunks").fetchone()[0])
print("with_embedding", cur.execute("select count(*) from chunks where embedding is not null").fetchone()[0])
print("missing_embedding", cur.execute("select count(*) from chunks where embedding is null").fetchone()[0])
con.close()
'@ | uv run python -

当前完成状态（2026-06-12）：
- items: 407
- chunks: 76566
- with_embedding: 76566
- missing_embedding: 0

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
- 可以删除 log\rag-full-library-* 和 log\rag-evidence-search-*。
- 不删除 .workspace\501-mno2-zn。
- 不删除 .zot\state\pdf_cache.sqlite。
- 不删除 .workspace\_models，除非明确不再使用本地模型缓存。
```

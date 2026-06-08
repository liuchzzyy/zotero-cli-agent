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

如果在本仓库内单独执行 metadata cleanup，先读取 Zotero 条目 metadata。默认导出命令必须同时跳过已清理 tag 和不需要清理的 holding collections：
uv run zot --json --detail full summarize-all --exclude-tag workflow/metadata --exclude-tag update/metadata --exclude-collection-key JJ6JSGT5 --exclude-collection-key 6HREN2FT --limit 5000 > log\metadata-cleanup-YYYYMMDD-HHMM\metadata-export.json

默认排除集合：
- `80_TRASH` (`JJ6JSGT5`)：无关/丢弃 holding collection，不做 metadata cleanup。
- `90_ARCHIVE` (`6HREN2FT`)：归档 holding collection，不做日常 metadata cleanup。
- `40_WORKSPACE` (`AFTJQCQA`) 默认不排除；只有明确不需要清理 workspace 条目时，才额外追加 `--exclude-collection-key AFTJQCQA`，或在总控 wrapper 中使用 `-ExcludeWorkspaceMetadata`。

导出后检查 metadata-export.json 的 meta：
- `excluded_tags` 应包含 `workflow/metadata` 和 `update/metadata`。
- `excluded_collection_keys` 应默认包含 `JJ6JSGT5` 和 `6HREN2FT`。
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

本指令独立包含运行文件规则：import_list、checkpoint、summary、failed_results、progress 和恢复审计文件都放在 log\rss-daily-item-import_YYYY-MM-DD；不要放在仓库根目录散文件、tmp\ 或临时 .workspace\... 运行目录中。成功且 failed=0 时默认清理本次 log 目录；失败、中断或需要恢复时保留该目录。

日常运行不要手动拆开清洗/导入步骤，直接调用 wrapper。默认调用会重新打开一个新的 PowerShell 窗口，实际 import 在新窗口中运行；wrapper 把本次 import_list、checkpoint、summary、failed_results、`run.log`、`progress.jsonl` 等运行文件放到 log\rss-daily-item-import_YYYY-MM-DD，并在 failed=0 成功完成后自动删除本次 log 目录：
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-daily-rss-doi-import.ps1 -Date YYYY-MM-DD -ProgressIntervalSeconds 5

推荐直接在 PowerShell 中运行 wrapper，保留新窗口输出；进度以新窗口输出、`run.log`、`progress.jsonl` 和 import_summary.json 为准。只有调试/CI 才追加 `-RunInCurrentWindow`。

默认读取：
E:\Desktop\CodingDaily\rss-cli-agent\storage\exports\daily_exports\YYYY-MM-DD.selected.json

GitHub Actions 定时运行：
- workflow: `.github/workflows/daily-rss-zotero-import.yml`
- 定时：北京时间每天 03:10；GitHub cron 使用 UTC，所以配置为 `10 19 * * *`。
- JSON 来源：`https://raw.githubusercontent.com/liuchzzyy/rss-cli-agent/main/storage/exports/daily_exports/YYYY-MM-DD.selected.json`
- 必需 Actions secrets：`ZOT_LIBRARY_ID`、`ZOT_API_KEY`。
- 可选 Actions secrets：`ZOT_CROSSREF_MAILTO`；`RSS_REPO_TOKEN` 仅在 rss-cli-agent 变为私有仓库时需要。
- GitHub runner 没有本地 Zotero SQLite；workflow 必须使用 `-SkipLibraryExport -SkipLocalDb`，让导入阶段只依赖 Zotero Web API。

如果 RSS selected JSON 在非默认位置，必须显式传入完整路径：
powershell -NoProfile -ExecutionPolicy Bypass -File tools\run-daily-rss-doi-import.ps1 -Date YYYY-MM-DD -SelectedJson "E:\Desktop\CodingDaily\rss-cli-agent\storage\exports\daily_exports\YYYY-MM-DD.selected.json" -ProgressIntervalSeconds 5

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

## Daily 00_UNSORTED Review

### 推荐给代理的直接提示词
```text
使用 skill zotero-cli-agent。
在 E:\Desktop\CodingDaily\zotero-cli-agent 下读取 Zotero 的 00_INBOX/00_UNSORTED 集合条目，按每 100 条为一批返回给我。

这是只读审阅流程，不写 Zotero，不改 zotero.sqlite，不生成 cleaned-metadata/update/delete 文件。默认直接在回复中返回结果；除非我明确要求保存快照，不要把结果散落到仓库根目录、tools\、tmp\ 或临时 .workspace\... 中。

执行顺序：
1. 先运行 `uv run zot --json collection list`，从当前 live collection tree 中确认 `00_INBOX/00_UNSORTED` 的 collection key。历史上常见 key 是 `QFGBGJTZ`，但每天都必须重新确认，不要直接复用旧 key。
2. 再运行 `uv run zot --json collection items <UNSORTED_COLLECTION_KEY>` 读取当前集合条目，记录本次总数和当前批次范围。
3. 按 Zotero 当前返回顺序从 1 开始编号。第一批返回 1-100；我说“下一批”时返回 101-200，依此类推。
4. 每条只返回四列，固定表头必须写成：`序号 / key / 中文标题 / 期刊`。
5. 推荐用 Markdown 表格返回，表头固定为：`| 序号 | key | 中文标题 | 期刊 |`。
6. 期刊字段优先取 `extra.publicationTitle`，没有时再取 `extra.journalAbbreviation`，再没有时取 `extra.publisher`；期刊名保持 Zotero 原文，不强行翻译。
7. 标题翻译成中文时保留专有名词、缩写、模型名、材料名和化学式的准确性，例如 MnO2、Zn2+、CO2、LiFePO4、LLM、RAG、VSR、MXene 不要拆坏或过度意译。
8. 返回前说明：`第一批：1-100 / 共 N 条` 或 `第 X 批：A-B / 共 N 条`。

可用的字段抽取命令示例：
$env:PYTHONIOENCODING='utf-8'
$j = uv run zot --json collection items <UNSORTED_COLLECTION_KEY> | ConvertFrom-Json
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

如果我后续要根据序号删除、移动或保留条目，必须把本次审阅输出对应的 number-to-key 映射视为唯一依据。不要在集合变化后重新读取并套用旧序号；执行任何写操作前先复述将要处理的序号、key 和目标集合，等我确认。
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
对尚未带有 `workflow/ai_note` 或旧 `update/AInote` 的非书籍条目，读取所有本地 PDF 附件，使用 MinerU 抽取 Markdown 和图片，经 CLIProxyAPI 的 gpt-5.4（reasoning effort=`high`）生成“AI条目分析 - <title>”note，写回 Zotero Web API，并给父条目打 tag `workflow/ai_note`。

本指令独立包含运行文件规则：checkpoint、preview、results、failures、notes、MinerU 临时资产和 batch logs 都放在 log\ai-note-analysis-batch-YYYYMMDD-HHMMSS；不要放在仓库根目录散文件、tmp\ 或临时 .workspace\... 运行目录中。完整成功并复核无误后清理本次目录；失败、中断、等待审查或需要保留 MinerU 原始材料时保留。

默认命令。wrapper 默认把 checkpoint、preview、results、failures、notes、MinerU 临时资产和 batch logs 放到 log\ai-note-analysis-batch-YYYYMMDD-HHMMSS，并在完整成功后自动清理本次 log 目录：
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
执行与日志规则：
- 默认通过对应 wrapper 重新打开新的 PowerShell 窗口运行；除非调试或 CI，不要追加 `-RunInCurrentWindow`。
- 保留新窗口，进度以新窗口输出和运行目录中的 `run.log`、`progress.jsonl` 为主；不要把额外 watch 命令当作主进度来源。
- 汇报进度必须基于 wrapper 输出、`run.log`、`progress.jsonl`、`logs\index.log`、`logs\embed.log`、`rag.idx.sqlite` 实际产物变化，不要只说“已开始”。
- 所有 stdout/stderr、中间文件和诊断日志都必须放在各自 `log\...` 运行目录；不要散落到仓库根目录、`tools\`、`src\zotero_cli_workflows\`、`tmp\` 或临时 `.workspace\...` 中。

使用 E:\Desktop\CodingDaily\zotero-cli-agent\tools\run-rag-full-library.ps1 为 Zotero 含 PDF 的父条目建立/更新 RAG 索引并回填 embedding，不要手动逐条添加 workspace item，不直接写 rag.idx.sqlite。查证据使用 E:\Desktop\CodingDaily\zotero-cli-agent\tools\run-rag-evidence-search.ps1，不要临时拼长命令。

默认目标：
- workspace 名称：full-library-rag。
- 默认集合：00_PROJECT_INBOX + 00_TOPIC_INBOX；wrapper 默认参数已经设置为 `-WorkspaceName full-library-rag -Collections "00_PROJECT_INBOX,00_TOPIC_INBOX"`。
- 条目范围：本地 Zotero SQLite 中 `00_PROJECT_INBOX` 与 `00_TOPIC_INBOX` 两个集合的并集，再筛选“至少有一个本地存在 PDF 附件”的父条目。
- 索引方式：phase-by-phase。先维护 .workspace\full-library-rag\workspace.toml；再调用 uv run zot workspace index full-library-rag --extractor mineru --progress-lines --item-progress --no-embed，让所有待处理条目先完成 PDF 抽取、chunk、BM25；最后统一调用 uv run zot workspace embed full-library-rag --progress-lines 回填 chunks.embedding IS NULL。
- 增量规则：workspace 只新增缺失 key；RAG index 只索引尚未进入 rag.idx.sqlite 的 item key；embedding 只回填 chunks.embedding IS NULL 的 chunk；PDF 文本抽取复用 .zot\state\pdf_cache.sqlite。
- index 阶段按 Zotero 父条目逐个处理、逐个 commit，但只写 BM25，不生成 embedding；中断后重跑会跳过已进入 rag.idx.sqlite 的 item key，继续剩余条目。embed 阶段按 chunk 批量提交，并在 provider 请求开始、等待、内部进度和 batch 完成时输出进度行；中断、provider 断连或手动停止后重跑会跳过已有 embedding 的 chunk。
- 本地 sentence-transformers 默认使用 CPU：安装 `uv sync --dev --extra mcp --extra local-embeddings-cpu`，并在 `.zot/config.toml` 的 `[embedding]` 里设置 `device = "cpu"`。GPU 运行使用 `uv sync --dev --extra mcp --extra local-embeddings-gpu`，并设置 `device = "cuda"`，也可以在 wrapper 中用 `-EmbeddingDevice cuda` 临时覆盖。同一个 `.venv` 不能同时安装 CPU 和 CUDA 两份 torch wheel；CUDA wheel 仍可通过 `device = "cpu"` 或 `-EmbeddingDevice cpu` 走 CPU fallback，不要为此创建 `.venv-gpu`。
- 本机 GPU 路径已验证为：NVIDIA GeForce GTX 960M + NVIDIA driver 522.25 + torch 2.7.1+cu118 + CUDA runtime 11.8。GTX 960M 只有 4GB 显存，`.zot/config.toml` 初始建议 `batch_size = 1`；确认稳定后再调大。GPU 全量 embedding 前必须先跑 `nvidia-smi` 和 PyTorch CUDA 检查，确认 `torch.cuda.is_available()` 为 true。

集合参数：
- wrapper 支持 `-Collections`，值为逗号分隔的 collection 名称或 key；inventory 阶段会对这些集合取并集并去重，再筛选“至少有一个本地存在 PDF 附件”的父条目。
- 当前默认集合限定命令会维护 .workspace\full-library-rag\workspace.toml，并索引到 .workspace\full-library-rag\rag.idx.sqlite。

本指令独立包含运行文件规则，并区分持久状态和本次运行文件：.workspace\full-library-rag 和 .zot\state\pdf_cache.sqlite 是持久 workspace/index/cache，不是清理对象；inventory、临时脚本、运行日志和临时诊断文件放在 log\rag-full-library-YYYYMMDD-HHMMSS。不要把本次运行文件放在仓库根目录散文件、tmp\ 或额外临时 .workspace\... 目录中。完整成功并复核无误后可清理本次 log 目录；失败、中断或需要审查时保留。单独后台回填 embedding 时可使用 log\rag-embedding-backfill，但 wrapper 的标准日志位置仍是本次运行目录下的 logs\embed.log。

默认 dry-run。运行文件默认放到 log\rag-full-library-YYYYMMDD-HHMMSS，dry-run 成功后会自动清理；如果要审查 inventory，加 -KeepLog：
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-full-library.ps1 -DryRun -ScanLimit 100 -KeepLog
默认会打开新 PowerShell 7/pwsh 窗口；调试时才追加 `-RunInCurrentWindow`。

正式增量运行。成功后自动删除本次 log\rag-full-library-YYYYMMDD-HHMMSS 运行目录；持久 workspace/index 仍保留在 .workspace\full-library-rag：
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-full-library.ps1
正式运行顺序是 inventory -> 全部待处理条目 item index/BM25 -> 全部缺失 chunks embedding 回填。不要手动单独启动后台 backfill，除非 wrapper 无法满足排查需求。

只回填旧索引 embedding，不重跑 PDF 提取或 index。适用于 rag.idx.sqlite 已有 chunks 但 chunks.embedding 为空或部分为空的情况：
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-full-library.ps1 -EmbedOnly -KeepLog

只小批量测试 GPU embedding，不重跑 PDF 提取或 index：
uv run python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)"
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-full-library.ps1 -EmbedOnly -EmbedLimit 100 -EmbeddingDevice cuda -KeepLog

00_PROJECT_INBOX + 00_TOPIC_INBOX 默认正式运行。长任务建议加 -KeepLog，方便完成后复核 index.log：
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-full-library.ps1 -KeepLog

边界：
- 默认不排除 book/bookSection，因为 RAG 的目标是“集合内含 PDF 条目”，不是 AI note 论文分析。
- 无本地 PDF 文件的条目不进入 workspace；有 Zotero PDF 记录但本地文件缺失的条目会统计为 pdf_but_missing_local_file。
- 现有 workspace index 的索引增量粒度是 item key。已索引条目的 PDF 或 metadata 后续变化不会自动重建；如果确认大量 PDF/metadata 已变更，用 -ForceRebuild 全量重建。-ForceRebuild 会先重建 BM25-only index，再统一回填新 chunks 的 embedding。
- embedding 增量粒度是 chunk。若 index 已 up-to-date 但 chunks.embedding 缺失，优先用 wrapper 的 -EmbedOnly 或自动 embed 阶段回填，不要为此用 -ForceRebuild。
- 不直接写 rag.idx.sqlite；RAG index 只通过 zot workspace index 生成，embedding 只通过 zot workspace embed 回填，避免破坏索引结构。
- 不删除 .workspace\full-library-rag，也不删除 .zot\state\pdf_cache.sqlite；它们是持久 workspace/index/cache，不是运行中间文件。

实时进度：
- 所有子命令（inventory、index、embed）的 stdout/stderr 会逐行输出到主窗口，并追加写入对应日志文件，不再打开额外 watcher 窗口。进度以主窗口实时输出为主，`run.log`/`progress.jsonl` 和子命令日志为辅。
- inventory 阶段会显示 scanned/local_pdf_items/pdf_but_missing。
- inventory 阶段还会显示 indexed_chunk_count、chunks_with_embeddings、chunks_missing_embeddings；如果 chunks_missing_embeddings > 0 且没有 -NoEmbed/-ForceRebuild，wrapper 只记录缺口，等 item index 完成后统一运行 logs\embed.log 中的 embedding backfill。
- index 阶段默认使用 `--progress-lines --item-progress --no-embed`，按条目输出 `[item:start]`、`[item:N:extract:cache]`、`[item:N:extract:upload]`、`[item:N:extract:process]`、`[item:N:extract:download]`、`[item:pdf-error]`、`[item:done]` 等逐行进度。
- embed 阶段默认使用 `--progress-lines`，按批输出 `[embed:start]`、等待 provider 时按 `-EmbedHeartbeatSeconds` 输出 `[embed:wait]`、provider 内部分批完成时输出 `[embed:provider]`、batch 完成时输出 `[embed:done]`，commit 后输出 `[embed] attempted=... stored=... skipped=... last_id=... rate=... eta=...`；provider 断连时会按参数重试并继续可恢复提交。
- `[item:done]` 表示该 item 已写入并 commit 到 rag.idx.sqlite；中断重跑时这类 key 会被跳过。
- 所有运行日志写入 log\rag-full-library-YYYYMMDD-HHMMSS\logs\inventory.log、log\rag-full-library-YYYYMMDD-HHMMSS\logs\index.log 和 log\rag-full-library-YYYYMMDD-HHMMSS\logs\embed.log。
- 可用 rag.idx.sqlite 中的 distinct item_key 数、chunks 数、embedding IS NOT NULL/IS NULL 数复核实际进展；不要直接修改该 SQLite。

查证据：
- 默认使用 wrapper，输出和日志在 log\rag-evidence-search-YYYYMMDD-HHMMSS；需要保留结果时加 -KeepLog。
- BM25 已完成但 embedding 未完成时，用 BM25 + rerank：
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-evidence-search.ps1 -Question "zinc manganese battery electrolyte evidence" -Mode bm25 -TopK 8 -RerankTopN 50 -KeepLog
- BM25 和 BAAI/bge-m3 embedding 都完成后，用 auto 或 hybrid + rerank：
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-evidence-search.ps1 -Question "zinc manganese battery electrolyte evidence" -Mode auto -TopK 8 -RerankTopN 50 -KeepLog
- 只看正文 PDF 或补充信息 PDF 时，加 -PdfKind main 或 -PdfKind supplementary。
- 给代理消费结构化结果时，加 -Json；人工查看时默认是 human-readable。若 reranker 配置不可用，加 -NoRerank 先退回 BM25/hybrid 原始排序。

中间文件清理：
- 默认会删除临时 inventory_full_pdf_workspace.py。
- 完整成功后脚本会删除本次 log\rag-full-library-YYYYMMDD-HHMMSS；如果 log\ 已空，也删除 log\。
- 如果需要保留 inventory.json 或运行日志用于审查，加 -KeepLog。
- 如果需要保留临时 inventory 脚本用于排查，加 -KeepInventory；这会保留本次 log 目录。
- 如果只想更新 workspace 不跑索引和 embedding，用 -NoIndex；成功后仍按默认清理本次 log 目录，除非加 -KeepLog。
- 如果只想回填 embedding，不跑 PDF 提取或 item 索引，用 -EmbedOnly；可配合 -EmbedBatchSize、-EmbedLimit、-EmbeddingDevice、-EmbedMaxRetries、-EmbedRetrySleep、-EmbedHeartbeatSeconds 控制批量、设备、重试和 provider 等待心跳。
- NVIDIA 驱动安装完成并验证后，可以删除安装中间文件：`C:\Users\chengliu\Downloads\NVIDIA`、`C:\NVIDIA\DisplayDriver\522.25` 和 `%TEMP%\NvidiaLogging`；不要删除已安装的 `C:\Program Files\NVIDIA Corporation`。

常用命令：
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-full-library.ps1 -DryRun -ScanLimit 500 -KeepLog
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-full-library.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-full-library.ps1 -DryRun -KeepLog
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-full-library.ps1 -KeepLog
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-full-library.ps1 -EmbedOnly -KeepLog
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-full-library.ps1 -EmbedOnly -EmbedLimit 100 -EmbeddingDevice cuda -KeepLog
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-full-library.ps1 -NoIndex
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-full-library.ps1 -ForceRebuild
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-evidence-search.ps1 -Question "zinc manganese battery" -Mode auto -TopK 8 -RerankTopN 50 -KeepLog
pwsh -NoProfile -ExecutionPolicy Bypass -File tools\run-rag-evidence-search.ps1 -Question "zinc manganese battery" -Mode bm25 -PdfKind main -TopK 8 -KeepLog
```

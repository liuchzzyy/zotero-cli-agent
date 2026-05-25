## Clean-up all metadata
这是当前推荐的标准流程，可以作为下次批量 metadata 清洗的默认做法。

### 目标
只做 metadata 的格式清洗，不做事实改写，不做文献内容增删，不做字段重构。

### 适用范围
只允许清洗这些字段：

- `title`
- `abstractNote`
- `publicationTitle`
- `journalAbbreviation`
- `language`
- `publisher`

不要修改这些字段：

- `DOI`
- `url`
- `date`
- `pages`
- `ISSN`
- `extra.extra`
- `creators`
- `tags`
- `notes`

备注：

- `extra.extra` 不属于这套通用清洗流程；如果后续要处理，按单独专项规则做。
- 当前增量标签使用 `update/metadata`，用于跳过已处理条目。

### 前置认知
- 使用 skill `zotero-cli-agents`。
- `summarize-all` 读取的是本地 `zotero.sqlite`。
- `update` 写入走的是 Zotero Web API。
- 如果刚做过写入，但本地导出还没反映变化，先让 Zotero 完成同步，再重新导出。

### 标准流程
1. 导出待处理条目，默认跳过已经打过 `update/metadata` 的条目。

```powershell
uv run zot --json --detail full summarize-all --exclude-tag update/metadata > metadata-export.json
```

2. 如果只想先小批量试运行，加 `--limit`。

```powershell
uv run zot --json --detail full summarize-all --exclude-tag update/metadata --limit 200 > metadata-export.json
```

补充：

- `--detail full` 导出中包含 `writable_fields`，生成 JSONL 时只从这里挑允许回写的字段。
- 长期批量处理优先依赖 `--exclude-tag update/metadata` 做增量跳过，不要把 `offset` 当成长期进度记录，因为库内容会变化。

3. 让 AI 基于导出的 metadata 生成 `cleaned-metadata.jsonl`。

规则：

- 只输出有变更的条目。
- 每行一个 JSON 对象。
- `fields` 中只放实际要修改的字段。
- 不确定时保持原值，不要猜测。
- 不要新增事实，不要翻译，不要重写学术内容，只做格式修复。

JSONL 格式示例：

```json
{"key":"ABC123","fields":{"title":"Clean title","abstractNote":"Clean abstract"}}
{"key":"XYZ789","fields":{"publicationTitle":"Journal of X","publisher":"Elsevier"}}
```

4. 先做 dry-run，先看计划，不正式写入。

```powershell
uv run zot --json update --from-jsonl cleaned-metadata.jsonl --dry-run
```

5. 等我确认后，再正式写入，并给成功处理的条目打 `update/metadata` 标签。

```powershell
uv run zot --json update --from-jsonl cleaned-metadata.jsonl --add-tag update/metadata
```

6. 写入后做同步和抽样校验。

建议：

- 先让 Zotero 同步。
- 再重新导出或抽查部分条目。
- 如果需要继续下一批，重复步骤 1 到 5，因为 `--exclude-tag update/metadata` 会自动跳过已处理条目。

7. 确认无误后再清理中间文件。

```powershell
Remove-Item metadata-export.json, cleaned-metadata.jsonl
```

### 清洗规则
- 去掉 HTML 标签。
- 规范异常空格。
- 修复断裂换行。
- 修复特殊符号与文本粘连。
- 保持原意，不改事实内容。
- 保持语言原样，不做中英互译。
- 空字段保持空，不要补写。

### 推荐给代理的直接提示词
```text
使用 skill zotero-cli-agents。
先读取 Zotero 条目 metadata，使用 summarize-all --detail full 导出，并排除 tag `update/metadata`。
只清洗这些字段的格式问题：title、abstractNote、publicationTitle、journalAbbreviation、language、publisher。
清洗目标：去掉 HTML 标签，修复异常空格、断裂换行、特殊符号粘连；保持原意，不改事实内容。
不要修改 DOI、url、date、pages、ISSN、extra.extra、creators、tags、notes。
只输出实际发生变更的条目，生成 cleaned-metadata.jsonl。
先执行 `uv run zot --json update --from-jsonl cleaned-metadata.jsonl --dry-run`，不要正式写入，等我确认。
```

## Daily RSS DOI Import
这是当前推荐的日常 RSS 文献导入入口，直接调用现成脚本，不要手动拆开执行两个 Python 脚本，除非是在排错。

### 目标
从 `E:\Desktop\CodingDaily\rss-cli-agent\storage\daily\当天.selected.json` 开始：

- 先生成 DOI 路由计划。
- 再把 DOI 导入 Zotero。
- 含作者告警的条目路由到 `00_INBOX_AA/<Author>`。
- 其他条目路由到 `00_INBOX_AA`。

### 标准入口
在 `E:\Desktop\CodingDaily\zotero-cli-agents` 下执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-rss-daily-doi-import.ps1
```

如果要指定日期：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-rss-daily-doi-import.ps1 -Date 2026-05-25
```

如果想让进度刷新更频繁：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-rss-daily-doi-import.ps1 -ProgressIntervalSeconds 5
```

### 运行特征
- 脚本内部会按顺序调用：
  - `scripts\clean_rss_selected_for_inbox.py`
  - `scripts\import_rss_inbox_plan.py`
- 导入过程中会持续显示进度：
  - `已处理/总数`
  - `new/reused/routed/failed`
  - `elapsed/eta`
- 如果检测到已有 `import_rss_inbox_plan.py` 进程在运行，脚本会直接报错退出，避免双进程同时写库。

### 收尾规则
- 如果有失败 DOI，会在仓库根目录导出：

```text
rss_failed_dois_YYYY-MM-DD.txt
```

- 如果全部成功，脚本会自动删除 `E:\Desktop\CodingDaily\zotero-cli-agents\tmp`。
- 如果导入失败，保留 `tmp` 现场用于排错，不要立即手动删除。

### 推荐给代理的直接提示词
```text
不要手动拆开执行 RSS DOI 导入流程。
直接在 E:\Desktop\CodingDaily\zotero-cli-agents 下调用 scripts\run-rss-daily-doi-import.ps1 做日常导入。
默认读取 rss-cli-agent\storage\daily\当天.selected.json。
如果需要，使用 -Date 指定日期，使用 -ProgressIntervalSeconds 调整进度刷新频率。
导入完成后检查根目录的 rss_failed_dois_YYYY-MM-DD.txt；如果没有失败且脚本成功结束，tmp 应该被自动删除。
```

## Remove Newer DOI Duplicates
这是当前推荐的 DOI 精确去重入口。规则固定为：同 DOI 的重复条目里，保留 `date_added` 更早的旧条目，删除 `date_added` 更晚的新条目。

### 判定规则
- 只使用 `DOI` 做精确判断。
- 不使用 `title` 做模糊或格式近似判断。
- 不看 collection；同一个独立条目放在不同 collection 不影响判定。
- 如果两个独立条目 DOI 一样，即使在不同 collection，也会被当成重复。

### 标准入口
在 `E:\Desktop\CodingDaily\zotero-cli-agents` 下执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\remove-newer-doi-duplicates.ps1
```

默认是 dry-run：

- 会先查询当前 Zotero 库中的 DOI 重复组。
- 会生成 `keep / delete` 计划。
- 不会真正删除任何条目。

正式执行删除时，加 `-Apply`：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\remove-newer-doi-duplicates.ps1 -Apply
```

### 可选参数
如果要调整每批删除的数量：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\remove-newer-doi-duplicates.ps1 -Apply -BatchSize 10
```

如果要指定 library：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\remove-newer-doi-duplicates.ps1 -Library user
```

### 运行特征
- 脚本内部会先调用：

```powershell
uv run zot --json --library user duplicates --by doi
```

- 查询完成后会显示：
  - DOI duplicate query 开始/结束时间
  - 找到多少组重复
- 生成计划时会持续显示：
  - `plan x/y`
  - 当前百分比
  - 每组的 `keep` 和 `delete`
- 正式删除时会持续显示：
  - 当前 batch 编号
  - 当前 batch 删除数量
  - overall 已完成数量和百分比
  - 本批实际 deleted keys

### 当前适用场景
- 适用于“新导入条目和旧库条目 DOI 一样，但 title 因大小写、空格、HTML 标签、上下标格式不同而看起来像不同条目”的场景。
- 不适用于“没有 DOI，只能靠标题近似判断”的去重场景。

### 推荐给代理的直接提示词
```text
不要用 title 模糊匹配做去重。
直接在 E:\Desktop\CodingDaily\zotero-cli-agents 下调用 scripts\remove-newer-doi-duplicates.ps1。
规则固定为：只按 DOI 精确判断；同 DOI 时保留 date_added 更早的旧条目，删除 date_added 更晚的新条目。
先执行默认 dry-run 看 keep/delete 计划；我确认后，再加 -Apply 正式删除。
```

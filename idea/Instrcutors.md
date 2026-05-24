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

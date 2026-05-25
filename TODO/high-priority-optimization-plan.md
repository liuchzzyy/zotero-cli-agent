# 高优先级优化设计说明（第 1 批）

本文档承接 [`docs/zh/reference/feature-manual.md`](./feature-manual.md) 第 14 章的高优先级热点，聚焦三组最值得先动手的能力：

1. `duplicates` 重复项检测
2. `workspace index/query` 工作区索引与检索
3. CLI / MCP / `schema` 一致性

目标不是立刻重写代码，而是先把“当前链路是什么、瓶颈在哪里、第一阶段应该怎么改、怎样验证改完没坏”讲清楚，便于后续逐项实施。

---

## 1. 总体优先级判断

这三组之所以应该先做，不是因为它们代码最多，而是因为它们分别卡住了三个关键面：

- `duplicates`：正确性和性能同时受限，真实大库上已经会影响可用性。
- `workspace index/query`：这是本仓库最重的本地计算链，也是后续 RAG 能力扩展的基础。
- CLI / MCP / `schema` 一致性：这是 agent-native 产品的接口地基，漂移一次就会同时影响文档、skill、脚本和 MCP client。

建议的实施顺序是：

1. 先固化 CLI / MCP / `schema` 一致性约束
2. 再改 `duplicates`
3. 最后做 `workspace index/query` 的结构化升级

原因很直接：

- 一致性约束先收紧，后面改命令面时不容易再漂。
- `duplicates` 改动范围相对集中，适合作为第一批性能重构。
- `workspace index/query` 最复杂，应该在契约和测试框架更稳后再推进。

---

## 2. `duplicates` 优化设计

## 2.1 当前实现链路

入口文件：

- `src/zotero_cli_agents/commands/duplicates.py`
- `src/zotero_cli_agents/core/reader.py::find_duplicates`
- `src/zotero_cli_agents/formatter.py::format_duplicates`

实际逻辑链：

```text
zot duplicates
  -> commands/duplicates.py
  -> reader.find_duplicates(strategy, threshold, limit)
  -> 读取最近 10000 条 itemID/key
  -> DOI 精确分组
  -> title 规范化精确分组
  -> 对 title singletons 做 SequenceMatcher O(n^2) 模糊比较
  -> 组装 DuplicateGroup
  -> formatter 输出
  -> 若发现重复项，CLI 以 EXIT_CONFLICT 退出
```

MCP 侧对应：

- `src/zotero_cli_agents/mcp_server.py::_handle_duplicates`
- `src/zotero_cli_agents/mcp_server.py::duplicates`

现有测试：

- `tests/test_duplicates.py`

## 2.2 当前实现的真实问题

### A. 数据范围被硬编码截断

当前只取最近 `10000` 条：

```python
SELECT i.itemID, i.key
...
ORDER BY i.dateAdded DESC
LIMIT 10000
```

这会导致两个问题：

- 老库中的重复项可能永远不参与检测。
- “重复项是否存在”取决于最近窗口，而不是全库事实。

### B. title 模糊匹配是 O(n^2)

当前对规范化后只出现一次的 title 做两两 `SequenceMatcher` 比较。这在真实库规模上会迅速变慢，尤其是：

- DOI 缺失较多时
- 标题相近但不完全相等的条目较多时
- 用户用 `--by title` 或 `--by both` 时

### C. 候选召回和最终聚类耦合在一起

当前函数把这些事全塞在一起：

- 原始候选提取
- 规范化
- 相似度计算
- 分组去重
- 结果裁剪

这让后续很难只优化某一层。

### D. `limit` 是结果组裁剪，不是计算量裁剪

当前逻辑仍然会先做大部分比较，再在最后 `groups[:limit]`。这意味着：

- 对性能没有实质保护
- `limit` 只影响输出，不影响耗时

### E. 相似度解释性弱

返回结构里只有：

- `match_type`
- `score`
- `items`

但没有：

- 哪个字段命中
- 哪种规范化规则命中
- title 模糊匹配的证据或相似签名

对后续 agent 自动处理来说，可解释性不足。

## 2.3 第一阶段优化目标

第一阶段不要追求“最强 duplicate engine”，只追求四件事：

1. 去掉“最近 10000 条”这种硬截断
2. 把 title 模糊匹配从全量两两比较改成“先召回候选，再算相似度”
3. 让 `limit` 尽量更早起作用
4. 返回更可解释的匹配原因

## 2.4 推荐改造路径

### 阶段 1：拆函数职责

先把 `reader.find_duplicates()` 内部拆成几个私有函数：

- `_load_duplicate_candidates()`
- `_group_by_doi()`
- `_group_by_exact_normalized_title()`
- `_generate_title_candidate_pairs()`
- `_cluster_duplicate_pairs()`

先拆结构，不改行为，确保测试仍过。

### 阶段 2：改 title 候选召回

推荐先做“轻量 blocking”，不要一上来引入复杂向量检索。可选方案：

- 规范化标题后按前缀词分桶
- 按 token 集合的最小签名分桶
- 按长度窗口过滤

推荐的保守组合：

1. 先做规范化
2. 仅比较长度差在阈值内的标题
3. 仅在共享至少一个高信息 token 的桶内比较

这样可以把全量 O(n^2) 压到“分桶内局部比较”。

### 阶段 3：显式区分“召回分数”和“成组分数”

当前 `score` 混用了“匹配成立程度”和“组内最高相似度”的概念。建议拆成：

- `match_reason`
- `match_score`
- `match_features`

例如：

```json
{
  "match_type": "title_fuzzy",
  "match_score": 0.91,
  "match_reason": "normalized_title_similarity",
  "match_features": {
    "shared_tokens": ["attention", "transformer"],
    "length_delta": 4
  }
}
```

### 阶段 4：补充运行统计

建议在 JSON 输出里加一个轻量 `meta` 或 `stats`：

- 扫描条目数
- DOI 组数
- exact title 组数
- fuzzy 候选对数
- fuzzy 实际命中组数

这样后续做真实性能比较时才有依据。

## 2.5 不建议现在就做的事

- 不建议第一阶段就接入向量相似度做标题查重。
- 不建议第一阶段就把 `duplicates` 变成可写命令。
- 不建议为了性能直接把逻辑全塞回 SQL。

原因是：

- 现在的核心问题是“算法结构”，不是“缺一个模型”。
- `duplicates` 目前只是检测命令，先把检测面做好更稳。
- SQL 过重会把逻辑解释性和可测试性一起拉低。

## 2.6 测试补强建议

现有 `tests/test_duplicates.py` 只覆盖小 fixture 的功能正确性。建议新增：

1. 大样本合成测试
   - 构造几百到几千条 title，验证候选召回不会退化成全量两两比较。
2. 全库而非最近窗口测试
   - 验证不会因时间窗口漏掉老数据。
3. 解释字段测试
   - 验证 `match_reason` / `match_features` 存在且稳定。
4. CLI exit 语义测试
   - 保持“发现重复项时返回 `EXIT_CONFLICT`”的行为不回归。

---

## 3. `workspace index/query` 优化设计

## 3.1 当前实现链路

入口文件：

- `src/zotero_cli_agents/commands/workspace.py`
- `src/zotero_cli_agents/core/workspace.py`
- `src/zotero_cli_agents/core/rag.py`
- `src/zotero_cli_agents/core/rag_index.py`

建索引链：

```text
zot workspace index NAME
  -> 读取 workspace TOML
  -> RagIndex(NAME.idx.sqlite)
  -> 可选 force clear
  -> 跳过已 indexed key
  -> reader.get_item() / get_pdf_attachment()
  -> PDF 提取
  -> metadata chunk + PDF chunk
  -> tokenize + term frequency
  -> chunks / bm25_terms 写入 sqlite
  -> 计算 avg_doc_len / total_docs
  -> 如配置 embedding，则批量生成并写入 embedding
```

查询链：

```text
zot workspace query QUESTION --workspace NAME
  -> 打开 NAME.idx.sqlite
  -> 检查是否存在 embedding
  -> bm25_score_chunks() 读取全量 chunk 和相关 term
  -> semantic_score_chunks() 读取全量 embedding
  -> hybrid 时做 reciprocal_rank_fusion()
  -> format_workspace_query()
```

现有测试：

- `tests/test_workspace_rag.py`
- `tests/test_pdf_integration.py`

## 3.2 当前实现的真实问题

### A. “增量索引”只看 key，不看内容是否变了

当前增量判断只做：

- `idx.get_indexed_keys()`

这意味着下面这些变化不会触发重建：

- item 标题/摘要/tags 改了
- PDF 文件换了
- PDF 修改时间变了
- extractor 变了
- chunk 策略变了
- embedding provider / model 变了

这会造成“索引存在，但已经过时”的隐性错误。

### B. 索引过程没有明确 checkpoint

当前流程虽然分阶段，但持久化状态比较粗：

- chunk 已写入
- bm25 term 已写入
- embedding 可能还没写完
- meta 可能已经或尚未更新

如果中途失败，当前索引可能是部分完成态，但没有显式“第几阶段完成”的状态。

### C. 查询阶段大量全表读取

当前：

- BM25 直接 `get_all_chunks()`
- 再为所有 chunk 取 term tf
- semantic 直接 `get_all_embeddings()`

这对小工作区没问题，但对大工作区会出现：

- 内存放大
- 查询延迟上升
- 结果越多越慢

### D. 索引结构过于扁平

当前 `chunks` 表只存：

- `item_key`
- `source`
- `content`
- `doc_len`
- `embedding`

缺少：

- chunk 顺序
- 内容 hash
- extractor / chunker version
- item 级状态
- 上次索引时间

这限制了后续做增量重建和解释性输出。

### E. `workspace query` 的结果解释力还不够

当前用户拿到的是 chunk 排名结果，但很难回答：

- 为什么这条排前面
- 是 metadata 命中还是 PDF 命中
- 是 BM25 贡献大还是 semantic 贡献大
- 某篇论文是否多个 chunk 都命中了

## 3.3 第一阶段优化目标

第一阶段建议只做下面五件事：

1. 建立 item 级“是否过时”判断
2. 给索引过程加 checkpoint / manifest
3. 让 query 避免全量无差别扫描
4. 给结果增加解释字段
5. 保持现有 CLI 面基本不变

## 3.4 推荐改造路径

### 阶段 1：给索引加 manifest / state 表

建议在 `RagIndex` 新增至少两张表：

- `item_state`
- `index_manifest`

`item_state` 推荐字段：

- `item_key`
- `item_hash`
- `pdf_path`
- `pdf_mtime`
- `extractor`
- `chunker_version`
- `embedding_provider`
- `embedding_model`
- `indexed_at`
- `status`

`index_manifest` 推荐字段：

- `schema_version`
- `extractor`
- `chunker_version`
- `embedding_provider`
- `embedding_model`
- `built_at`

这样才能判断：

- 这个 item 是否需要重建
- 整个 index 是否因为配置变化需要整体失效

### 阶段 2：把索引过程改成 item 级事务

比起“全量大事务”，更稳的做法是：

1. 先算出待重建 item 列表
2. 对每个 item：
   - 删除该 item 旧 chunk
   - 重建 metadata chunk
   - 重建 PDF chunk
   - 写入 bm25 term
   - 如可用则写 embedding
   - 更新 `item_state`

这样中断时只会影响当前 item，不会让整个库进入难解释状态。

### 阶段 3：BM25 查询改成“按 query term 反查候选”

当前 BM25 已经把 query term 的 df 做成 bulk SQL，但仍然会：

- 读取所有 chunk
- 读取所有 chunk 的 tf

更合理的路径应该是：

```text
query terms
  -> 从 bm25_terms 反查命中的 chunk_id
  -> 汇总只相关的 chunk
  -> 计算这些 chunk 的 BM25
  -> 排序取 top N
```

这会把查询复杂度从“全表扫描”变成“命中项扫描”。

### 阶段 4：semantic 查询加候选截断

当前 semantic 是对全量 embedding 做相似度计算。若不引入外部向量库，第一阶段也至少应：

- 先限制到前若干候选 chunk
- 或先按 BM25 做候选召回，再在候选上做 semantic rerank

推荐的保守策略：

- `semantic` 模式：仍可全量，但要明确大库成本
- `hybrid` 模式：默认先 BM25 召回 top M，再做 semantic rerank

这样改动小，而且最符合现在的 sqlite 结构。

### 阶段 5：返回解释字段

`workspace query` 的每条结果建议增加：

- `source`
- `item_key`
- `chunk_id`
- `bm25_score`
- `semantic_score`
- `final_score`
- `rank_reason`

例如：

```json
{
  "item_key": "ABC123",
  "source": "pdf",
  "chunk_id": 42,
  "bm25_score": 8.14,
  "semantic_score": 0.77,
  "final_score": 0.032,
  "rank_reason": "hybrid_rrf"
}
```

## 3.5 当前代码里最值得先改的点

按改造收益排序：

1. `core/rag_index.py`
   - 先扩 schema，支持 item 级状态
2. `commands/workspace.py::workspace_index`
   - 改增量重建判定
3. `core/rag.py::bm25_score_chunks`
   - 从全量扫描改为命中候选扫描
4. `commands/workspace.py::workspace_query`
   - 加解释字段和候选截断

## 3.6 测试补强建议

建议补下面几类测试：

1. stale index 检测测试
   - item metadata 改变后，增量索引能识别并重建。
2. extractor 切换测试
   - `pymupdf` 与 `mineru` 切换后，旧索引不会被误认为最新。
3. 中断恢复测试
   - 模拟中途失败，确认不会把整个 index 置于不可解释状态。
4. query 候选缩减测试
   - 验证查询不再依赖全量 chunk 扫描。
5. 结果解释字段测试
   - JSON 输出中包含新的排序解释字段。

---

## 4. CLI / MCP / `schema` 一致性优化设计

## 4.1 当前实现链路

相关文件：

- `src/zotero_cli_agents/cli.py`
- `src/zotero_cli_agents/commands/schema.py`
- `src/zotero_cli_agents/mcp_server.py`
- `docs/agent-interface.md`
- `skill/zotero-cli-agents/SKILL.md`

当前结构是：

```text
Click command tree
  -> zot schema 从 Click 动态提取参数树
  -> CLI help 来自 Click
  -> MCP tools 在 mcp_server.py 中手工定义
  -> docs / skill 由人工维护
```

这个结构的优点是 CLI 与 `schema` 比较接近，因为 `schema` 直接从 Click 树取。

但它仍然有几个明显缺口。

## 4.2 当前实现的真实问题

### A. safety tier 只按顶层命令名粗分

`commands/schema.py` 里 `_SAFETY_TIER` 现在只看顶层名字：

- `add`
- `update`
- `note`
- `attach`
- `delete`
- `update-status`

这会直接导致：

- `collection create/delete/move/rename/reorganize` 在 schema 中仍显示成 `read`
- `trash restore` 在 schema 中仍显示成 `read`
- `workspace delete` 虽然是本地删除，也仍是 `read`

也就是说，当前 `schema` 的安全分层只对一部分命令准确。

### B. CLI 与 MCP 是“双源定义”

CLI 命令定义在 `commands/*.py`，MCP tools 定义在 `mcp_server.py`。两边并不是从一个统一注册表自动生成的，因此天然有漂移风险，例如：

- CLI 有、MCP 没有
- MCP 有、CLI 没有
- 参数名不同
- 默认值不同
- 文档说明不同

### C. docs / skill 示例容易漂移

虽然 `schema` 能反映真实 CLI，但：

- `docs/`
- `SKILL.md`
- README 里的例子

仍然是手工维护的文本。

这意味着只要改命令参数而没补文档，就会出现表面一致、实际使用不一致的问题。

### D. structured MCP output 还缺“全量回归保障”

最近已经修复了 `structuredContent` 为 `None` 的问题，但当前测试仍偏抽样：

- 已有 `search` tool 的输出 schema 测试
- 已有低层 `call_tool` 对 `structuredContent` 的验证

但还没有覆盖“所有 MCP tools 都应该有稳定 output schema”这一层。

## 4.3 第一阶段优化目标

第一阶段建议只做四件事：

1. 把 `schema` 的 safety tier 精度拉到子命令级
2. 建一个“CLI 命令面 vs MCP tool 面”的自动对照测试
3. 建一个“docs/skill 示例 vs schema” 的轻量校验
4. 对所有 MCP tools 增加结构化输出回归测试

## 4.4 推荐改造路径

### 阶段 1：把 safety tier map 改成全路径

当前 `_SAFETY_TIER` 只支持顶层命令。建议改成 dotted path 或 tuple path，例如：

```python
{
    ("add",): "write",
    ("update",): "write",
    ("delete",): "destructive",
    ("collection", "create"): "write",
    ("collection", "delete"): "destructive",
    ("trash", "restore"): "write",
}
```

回退逻辑可以是：

1. 先查完整路径
2. 再查顶层路径
3. 否则默认 `read`

这样改动最小，但能显著提高 `schema` 可信度。

### 阶段 2：建立接口对照矩阵

建议新增一个小型 contract test，自动收集：

- CLI schema 的命令树
- MCP tool registry

然后校验：

- 哪些 CLI 命令被声明为应暴露 MCP
- 对应 MCP tool 是否存在
- 参数名是否兼容
- 默认值是否兼容

不要求 CLI 与 MCP 完全 1:1，但必须是“明确允许的不一致”，而不是“无意漂移”。

### 阶段 3：收紧 MCP output schema 回归测试

建议新增一个测试矩阵，至少检查：

- 所有 `@mcp.tool()` 注册的 tool 都有 `output_schema`
- 抽样或参数化检查多类 tool 的 `structuredContent` 非空
- 返回值顶层必须是 JSON object，而不是裸字符串或裸列表

这样后面再新增 tool 时，不会回到“只能从 `content[0].text` 里抠 JSON”的状态。

### 阶段 4：把文档示例校验自动化

建议不要一开始做复杂 doc parser，第一阶段只做够用的校验：

1. 抽取 `SKILL.md` 中的 `zot ...` 示例
2. 抽取关键文档中的命令示例
3. 用 `zot schema` 或 `zot --help` 验证这些 flags 是否真实存在

这样至少能防住最常见的示例漂移。

## 4.5 当前代码里最值得先改的点

1. `src/zotero_cli_agents/commands/schema.py`
   - 先支持 path-level safety tier
2. `tests/test_agent_interface.py`
   - 扩展 schema 与 help 的漂移校验
3. `tests/test_mcp_server.py`
   - 扩展为全 tool 的 output schema/structured output 回归
4. 新增 contract test
   - 专门检查 CLI 命令面与 MCP tool 面关系

## 4.6 测试补强建议

建议新增：

1. `collection.*` 与 `trash.restore` safety tier 测试
2. MCP 全 tool `output_schema` 存在性测试
3. CLI/MCP 参数对照测试
4. skill 示例漂移测试

---

## 5. 推荐实施顺序

如果下一步开始真正改代码，推荐按下面顺序推进：

1. 先改 `schema` safety tier 到子命令级，并补测试
2. 再加 MCP tool registry / structured output 回归测试
3. 然后重构 `duplicates` 为分阶段候选召回
4. 最后升级 `workspace index/query` 的索引状态和查询候选机制

这样做的好处是：

- 前两步先把接口护栏立起来
- 中间一步先拿一个中等复杂度功能做性能重构
- 最后再动最重的 RAG 链路

---

## 6. 每组功能的落地完成标准

### `duplicates`

达到下面标准，才算第一阶段完成：

- 不再依赖“最近 10000 条”硬截断
- title 模糊匹配不再走全量 O(n^2)
- JSON 输出能解释为什么判重
- 现有 CLI exit 语义保持不变

### `workspace index/query`

达到下面标准，才算第一阶段完成：

- 能识别 item 级 stale index
- 索引中断后状态仍可解释
- query 不再依赖全量 chunk/embedding 读取
- 输出包含基本排序解释字段

### CLI / MCP / `schema`

达到下面标准，才算第一阶段完成：

- safety tier 至少对子命令级准确
- MCP tools 全部有结构化输出 schema 回归保护
- CLI/MCP 命令面对照有自动测试
- skill / docs 示例至少有轻量漂移检查

---

## 7. 后续文档建议

如果这三组开始进入实施阶段，建议再分别补三份更细的执行文档：

1. `duplicates-refactor-plan.md`
2. `workspace-rag-refactor-plan.md`
3. `interface-consistency-contracts.md`

那三份文档就不再讲“为什么做”，而直接讲：

- 数据结构怎么改
- 具体函数怎么拆
- 测试怎样分批补
- 哪些改动必须保持向后兼容


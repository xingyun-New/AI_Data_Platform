# 知识图谱改进路线图（Knowledge Graph Roadmap）

本文档汇总了对项目知识图谱（`kg_entities` / `kg_document_entities` / `kg_document_relations`
及其服务 `backend/app/services/kg_service.py`）的改进讨论。包含已识别的限制、本轮落地项、
后续迭代计划，以及经过复盘**已撤回的错误建议**。

> 配套阅读：[KNOWLEDGE_GRAPH.md](KNOWLEDGE_GRAPH.md)（当前架构与接口文档）

---

## 一、已识别的限制

### 1.1 信息孤岛

- `kg_min_shared_entities` 固定为 2：共享实体数 < 2 的文档对建不了边
- `kg_max_edges_per_doc` 固定为 50：枢纽文档的真实强关联会被截断
- 一跳扩展只支持一层，间接关联（A↔B↔C）找不到

### 1.2 LLM 抽取的不稳定

- 单次 LLM 调用即入库，没有"多次一致性"校验
- `confidence` 字段当前硬编码为 1.0
- `_write_document_entities` 先删后插：LLM 若本次漏抽，已有正确关联被静默丢失
  - **本轮改动 3 解决**

### 1.3 高频噪声实体污染评分

- `retrieve_by_entities` 用 `COUNT(*)` 作为 `direct_score`，"本公司"、"领导"等高频实体
  与关键稀有实体（合同号等）同等权重
  - **本轮改动 1 解决**
- 缺少黑名单机制，无法在抽取阶段阻断噪声实体
  - **本轮改动 2 解决**

### 1.4 实体归一化的局限

- 仅在同类型内合并（正确设计，勿改）
- SQLite 场景下 `_find_similar_entity` 是全表内存扫描，超过 5 万实体/类型会慢
- 中文归一化只做了 `casefold()`（对 CJK 是 no-op），未处理简繁体、缩写、空格差异

### 1.5 查询端脆弱性

- 查询实体抽取失败 → 图召回返回空，没有向量兜底
- 当前依赖 Dify 侧的条件分支做回退，无平台内原生支持
- 查询端 LLM 实体分类不稳定：DB 里 `customer: osram` 会被 query LLM 标成 `org`，
  `match_query_entities` 的类型过滤直接 miss 掉
  - **本轮改动 4 解决（跨类型精确兜底）**

### 1.6 架构耦合与运维缺口

- `knowledge_db_name` 硬编码等于 `filename`，且与 `dify_uploader` 的拼写错误
  `knowlege_db_name` 强耦合（见 `kg_service.retrieve_by_entities` 第 593 行注释）
- `mention_count` 仅计数，无时效衰减/置信度衰减
- 缺少实体合并/拆分/改名的管理后台
- 缺少图谱健康度指标（孤岛文档占比、平均度数、实体重复率等）

---

## 二、本轮落地（⭐⭐⭐ 优先级）

### 改动 1：实体 IDF 加权评分

**文件**：`backend/app/services/kg_service.py`

**内容**：在 `retrieve_by_entities` 中，将文档得分从"匹配实体数"改为"按实体
稀有度（IDF）加权求和"：

```
weight(entity) = 1 / log(1 + df(entity))
direct_score(doc) = Σ weight(e) for each matched entity e in doc
```

其中 `df(entity)` = 该实体在 `kg_document_entities` 中出现的**不同文档数**。

**效果**：只被 1 个文档提到的实体权重 ≈ 1.44，被 100 个文档提到的实体权重 ≈ 0.22，
高频无意义实体的影响被自然抑制。

### 改动 2：实体黑名单

**文件**：`backend/app/config.py`、`backend/app/services/kg_service.py`、`backend/.env`

**内容**：

- `Settings` 新增 `kg_entity_blacklist: str`（逗号分隔）和 `kg_entity_blacklist_set` property
- `normalize_entities`：过滤黑名单实体后再做 embedding（省 API 调用）
- `match_query_entities`：查询端同步过滤
- `.env` 提供示例 `KG_ENTITY_BLACKLIST=本公司,领导,相关方,公司,部门`

### 改动 3：并集增量合并（save_graph 不再丢数据）

**文件**：`backend/app/services/kg_service.py`

**内容**：

- `_write_document_entities` 不再删除文档的旧 `DocumentEntity` 行
- 采用 upsert：新抽到的 `(doc, entity, relation)` 三元组若库里不存在则新增，存在则跳过
- `_build_relations_for_document` 仍然基于"并集后的完整实体集合"重建边（边整体重建是安全的）

**取舍**：选择并集（用户确认）而非智能合并/置信度驱动。代价是 `DocumentEntity`
行会只增不减，需配套后续迭代的"定期清理"任务（见 §3.5）。

### 改动 4：查询端跨类型精确兜底

**文件**：`backend/app/services/kg_service.py`

**背景**：诊断 `osram 是谁` 在前端命中 0 的实际运行结果：

```
LLM extracted entities: [ { "name": "osram", "type": "org" } ]
Cross-type DB rows where LOWER(name)='osram':
  id=75 type=customer name='osram' aliases='["欧司朗"]'
match_query_entities returned: (empty)
```

Query 端 LLM 把 customer 误判成 org，类型过滤直接 miss。

**内容**：

- 新增 `_exact_match_entity_any_type(db, name)`：不带类型过滤的 name/alias 精确匹配，
  按 `mention_count DESC, id ASC` 排序取最"主流"的一个，处理跨类型歧义
- `match_query_entities` 调整匹配顺序：
  1. 同类型精确（原路径）
  2. **跨类型精确（新增兜底）**
  3. 同类型向量相似度

**刻意不做**：跨类型向量兜底。embeddings 是基于 `{type}: {name}` 计算的，
跨类型向量匹配会语义漂移，引入假阳性。

**副作用**：同名跨类型实体（罕见）会命中 `mention_count` 最高的那个；触发时
会记 `INFO` 日志。

---

## 三、后续迭代（⭐⭐ 优先级）

### 3.1 Dify 侧图+向量融合

在 Dify 工作流中增加条件分支：

- 图召回返回非空 → 用 `knowledge_db_names` 做 metadata 过滤后检索
- 图召回为空 → 直接走纯向量检索

参见 `backend/docs/KNOWLEDGE_GRAPH.md` 第 137-143 行已有建议。

### 3.2 中文归一化增强

在 `_normalize_name` 中增加：

- 简繁体转换（可引入 `opencc-python-reimplemented`）
- 常见缩写映射（配置文件维护 `"阿里"→"阿里巴巴集团"`）
- 空格/全角符号归一

### 3.3 前端实体管理界面

在 `frontend/src/pages/KnowledgeGraphPage.tsx` 增加：

- 实体编辑（改名、增删别名）
- 实体合并（选中多个 → 合并成一个，迁移所有 `DocumentEntity`）
- 实体拆分（一个实体 → 按文档集合拆分成多个）

### 3.4 图谱健康度指标

`GET /api/graph/stats` 扩展返回：

- 孤岛文档数/占比（`kg_document_relations` 中零边的文档）
- 平均度数、度数分布
- 候选重复实体对（同类型内 cosine 接近但未合并的）

### 3.5 定期清理任务（并集策略的配套）

新增管理接口或定时任务：

- 记录每个 `DocumentEntity` 的 "最近一次 LLM 命中时间戳"
- 若某关联连续 N 次重索引都未被命中，自动降低 `confidence` 或归档
- 避免 §2 改动 3 带来的无限增长

---

## 四、不确定价值（⭐ 优先级，需先评估）

### 4.1 多跳扩展（2 跳+）

- 收益：可能发现间接关联
- 风险：容易引入噪声文档、计算量指数增长
- 建议：先收集用户对"召回不足"的反馈，确认是否为主要矛盾

### 4.2 时间衰减

- `DocumentRelation.weight` 或 `Entity.mention_count` 按 `updated_at` 衰减
- 除非业务明确需要"近期文档权重更高"，否则不急

### 4.3 LLM 多次投票抽取

- 同一文档多跑 2-3 次抽取，取交集作为高置信实体
- 成本翻倍，只有当 LLM 抽取不稳定成为实际问题时才值得

---

## 五、已撤回的错误建议（反面教材）

复盘中发现以下建议**站不住脚**，记录于此避免未来重提。

### 5.1 "跨类型实体自动合并（cosine > 0.95）"

**为什么错**："小米" 可以是 `person` 也可以是 `product`，**本来就应该是两个实体**。
跨类型合并会引入类型污染，破坏系统的类型语义。

### 5.2 "把 kg_min_shared_entities 降到 1"

**为什么错**：降到 1 会让任何两篇提到同一个人名（如"张三"）的文档都建边。
在真实公司里，"张三"可能指几十个不同人，噪声会爆炸，且 `kg_max_edges_per_doc=50`
限流后反而会丢弃真正有价值的强关联。**正确方向是 IDF 加权（见 §2 改动 1）**，
按实体稀有度降低高频实体的权重。

### 5.3 "用文档 embedding 直接建边"

**为什么错**：Dify 后端本来就做向量检索。知识图谱的价值恰恰是提供**结构化
关联**——向量检索捕捉不到的东西。再在图里加向量相似边，等于用更慢的方式
做了一次向量检索，职责重叠。

### 5.4 其他分析错误（上轮对话中的失误）

- 错把"关系类型单一"当成缺陷：实际 `_dominant_relation_type` 已支持 7 种
  文档间关系（`same_project` / `same_customer` 等）
- 错把"embedding 静态不变"当成缺陷：实际 `_merge_entity` 已通过 `weighted_mean`
  在每次合并时更新质心向量

---

## 六、版本

- **2026-04-19**：创建文档，落地三星优先级改动（改动 1-3）
- **2026-04-19**：追加改动 4 —— 查询端跨类型精确兜底（诊断 `osram 是谁` 零命中后补）

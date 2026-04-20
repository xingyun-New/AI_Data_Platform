# 知识图谱增强检索（GraphRAG）

## 概述

本平台在"脱敏 → 索引 → Dify 上传"流水线里，同步从每份文档抽取**实体+关系**沉淀为知识图谱，并暴露 `POST /api/graph/retrieve` 接口供 Dify 工作流在 RAG 前先做"图召回"，避免直接向量检索时漏掉相关文档。

## 数据模型

三张表构成双层图，外加一列"主题向量"挂在文档本体上：

| 表/列 | 作用 |
| --- | --- |
| `kg_entities` | 归一化的实体节点（person / customer / project / product / org / contract / other），带 embedding |
| `kg_document_entities` | 边：Document --mentions / about / authored_by / belongs_to--> Entity |
| `kg_document_relations` | 边：Document ↔ Document（基于共享实体，无向；存储时 `src_id < dst_id`） |
| `documents.index_embedding` | 文档 index 的"主题签名"向量（由 purpose+summary+keywords+scenarios 拼接后 embedding），用于检索阶段做主题级 rerank |

## 构建流程

1. 文档通过 `POST /api/documents/{id}/generate-index` 或批量流水线时，`index_generator` 除了原有的索引元数据，还会**并行**调用 `graph_extract.txt` 抽取实体
2. `kg_service.save_graph()`：
   - 候选实体批量 embedding（DashScope `text-embedding-v4`）
   - **同类型内**按余弦相似度 ≥ `kg_entity_merge_threshold`（默认 0.88）合并已有实体；aliases 追加新字面形式；质心向量按加权均值更新
   - 写入 `kg_document_entities`
   - 用一条聚合 SQL 查出所有与新文档共享 ≥ `kg_min_shared_entities`（默认 2）实体的老文档，批量写 `kg_document_relations`；边数由 `kg_max_edges_per_doc`（默认 50）限流

## 相关配置（`backend/app/config.py`）

| 键 | 默认 | 作用 |
| --- | --- | --- |
| `kg_embedding_model` | `text-embedding-v4` | DashScope embedding 模型 |
| `kg_embedding_dim` | `1024` | 向量维度 |
| `kg_embedding_batch_size` | `10` | 单次 API 请求最大条数 |
| `kg_entity_merge_threshold` | `0.88` | 同类型实体合并的 cosine 阈值 |
| `kg_min_shared_entities` | `2` | 两文档共享实体数 ≥ N 才建边 |
| `kg_max_edges_per_doc` | `50` | 单文档最多保留的关系边数 |
| `kg_enable_index_rerank` | `True` | 是否启用"主题 rerank"二次筛选 |
| `kg_index_rerank_alpha` | `0.6` | 融合打分里 KG 实体分（归一化到 [0,1]）的权重 |
| `kg_index_rerank_beta` | `0.4` | 融合打分里 query 与 index embedding 余弦相似度的权重 |
| `kg_index_rerank_min_score` | `0.25` | 余弦低于此值的文档直接剔除（主要用于过滤"命中实体但主题不相关"） |
| `kg_index_rerank_pool_multiplier` | `2` | 初召回扩展到 `top_k * multiplier`，再 rerank 截到 `top_k` |
| `kg_query_use_automaton` | `True` | 查询侧 NER 启用 Aho-Corasick 快速路径，命中即跳过 LLM |
| `kg_query_automaton_min_length` | `2` | 入 automaton 的 surface form 最小长度，过滤 1 字实体的子串误匹配 |

## 查询侧 NER 加速（Aho-Corasick 快速路径）

`retrieve_by_query` 调用 LLM（`kg_query_model`，默认 `qwen3.5-flash`）从用户问题里抽实体，这一步的网络 + 生成时延（300–800 ms）是查询链路的主要瓶颈。由于被抽取的实体绝大多数都已经在 `kg_entities` 里有记录，我们在进程内维护一个基于 Aho-Corasick 的多模式字符串匹配器（见 `backend/app/services/kg_entity_matcher.py`），用 DB 字典做**本地 O(n+m)** 的命名体识别。

- **命中 ≥ 1**：直接把命中的 `entity_id` 喂给 `retrieve_by_entities`，**跳过 LLM NER + embedding 匹配**，延迟 < 5 ms。
- **命中 0**：回退到原先的 `extract_query_entities` + `match_query_entities` 路径，保底覆盖 automaton 认不出的新表述。
- **字典一致性**：每次查询前读一次 `SELECT MAX(updated_at) FROM kg_entities` 作为版本号；新增 / 合并实体会通过 SQLAlchemy 的 `onupdate=func.now()` 自动刷新该字段，下一次查询触发懒重建。
- **歧义消解**：同一位置被多个 surface form 命中时采用**最长匹配优先**；`kg_query_automaton_min_length`（默认 2）进一步阻止短字符串误匹配（例如人名"张三"出现在"张三丰"中）。
- **一键回退**：`kg_query_use_automaton=False` 就退回纯 LLM NER 路径，便于 A/B 或事故回滚。

多 worker（uvicorn 多进程）部署时每个进程各自维护一份 automaton，内存占用按实体数量线性增长，20k 实体场景下每进程约几十 MB，可忽略。

## 主题 rerank（二次筛选）

纯实体匹配只知道"哪些文档提到了这些实体"，无法区分"主题就是它"和"顺带提一句"。为此每份文档在 index 生成阶段会额外产出一个**主题向量**并存到 `documents.index_embedding`，检索时：

1. 提取 query 实体 与 query embedding（两路 I/O 并行）
2. 按实体 IDF 先粗召回 `top_k × kg_index_rerank_pool_multiplier` 份文档
3. 对候选文档计算 `cosine(query_vec, doc.index_embedding)`
4. 丢弃余弦 < `kg_index_rerank_min_score` 的（明显"跑题"的文档）
5. 按 `final = α × kg_norm + β × cosine` 重排，截取 `top_k`

返回的 `documents[*]` 会多两个字段 `kg_score`（原始实体分）和 `index_cosine`（与 query 的主题相似度），便于排障和 A/B。

把 `kg_enable_index_rerank` 设成 `false` 可一键回退到旧的实体 IDF 排序。

新文档走 `generate-index` 时会**自动**写入 `index_embedding`；存量文档需要调一次回填（见"运维建议"）。

## API 接口

### `POST /api/graph/retrieve`（无鉴权，供 Dify 调用）

```bash
curl -X POST http://<host>:8000/api/graph/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "A项目最近进展如何？", "top_k": 10, "department": null}'
```

响应：

```json
{
  "query": "A项目最近进展如何？",
  "matched_entities": [
    {"id": 42, "name": "A项目", "type": "project"}
  ],
  "documents": [
    {
      "doc_id": 17,
      "filename": "A项目周报.md",
      "knowledge_db_name": "A项目周报.md",
      "department": "研发部",
      "status": "uploaded",
      "score": 3.0,
      "matched_entities": [42]
    }
  ],
  "knowledge_db_names": ["A项目周报.md"]
}
```

### `GET /api/graph/document/{doc_id}`（鉴权）
返回该文档的实体+关联文档子图，供前端可视化。

### `GET /api/graph/entities`（鉴权）
实体列表，支持 `q`（名称/别名模糊）、`entity_type` 过滤、分页。

### `GET /api/graph/entities/{id}/documents`（鉴权）
列出引用某实体的全部文档。

### `GET /api/graph/stats`（鉴权）
实体/边数统计，以及按 `entity_type` 的分布。

### `POST /api/graph/rebuild`（鉴权）
对存量文档回填图数据。请求体：

```json
{
  "document_ids": null,
  "only_missing": true,
  "limit": null
}
```

- `only_missing=true`（默认）：仅处理 `kg_document_entities` 里还没有记录的文档
- `document_ids`：指定文档 id 列表；不传则处理所有 `status in (indexed, uploaded)` 的文档
- 重建时优先复用 index JSON 里已缓存的 `knowledge_graph` 字段，避免重复 LLM 调用

### `DELETE /api/graph/document/{doc_id}`（鉴权）
仅删除该文档的图边，实体节点保留。

---

## Dify 工作流接入步骤

在 Dify Studio 里打开你的聊天工作流，按下面的步骤改造：

### 1. 加 HTTP 请求节点（图召回）

放在"开始"节点之后、"知识检索"节点之前：

- **方法**：POST
- **URL**：`http://<backend-host>:8000/api/graph/retrieve`
- **Headers**：`Content-Type: application/json`
- **Body（JSON 模式）**：

```json
{
  "query": "{{#sys.query#}}",
  "top_k": 10
}
```

### 2. 用变量提取器拿到 `knowledge_db_names`

- 添加"变量提取器"节点（或"代码执行器"节点）
- 输入变量：上一步 HTTP 节点的 `body`
- 输出变量：`kb_names`（Array[String]）
- JSONPath / 代码：`$.knowledge_db_names`

### 3. 知识检索节点启用 metadata 过滤

在"知识检索"节点打开 "metadata 过滤" 选项：

- **字段**：`knowlege_db_name`（注意 Dify 里实际拼写 —— 见 `backend/app/core/dify_uploader.py` 第 48 行，这里保留了历史拼写）
- **操作**：`in`（包含于）
- **值**：`{{#extractor.kb_names#}}`

### 4. 兜底策略（可选但推荐）

为避免图召回返回空时知识检索也为空，用一个条件分支：

- 若 `length(kb_names) > 0` → 走上面的 metadata 过滤路径
- 否则 → 走**不加过滤**的原始知识检索（回退到纯向量检索）

### 5. 部门/权限透传（可选）

如果你想让图召回也遵循用户所在部门，Dify 前端可以把用户信息写入会话变量，然后 HTTP 节点的 body 里把 `department` 一起带过去：

```json
{
  "query": "{{#sys.query#}}",
  "top_k": 10,
  "department": "{{#conversation.user_department#}}"
}
```

---

## 运维建议

- **首次上线**：先跑 20-50 份真实文档，调 `GET /api/graph/entities?entity_type=project` 看看合并/拆分是否合理，再调整 `kg_entity_merge_threshold`
- **存量回填**：部署后立即调 `POST /api/graph/rebuild`，`only_missing=true` 增量处理
- **重索引**：当 `graph_extract.txt` 改动后，可带 `only_missing=false` 全量重跑（可以先 `DELETE /api/graph/document/{id}` 清理旧边，或直接复用同一文档 id，`save_graph` 内会覆盖）
- **明星实体治理**：`GET /api/graph/entities` 按 `mention_count desc` 可以发现"本公司"这类高频无意义实体；未来可加"黑名单"字段阻止其参与建边
- **index 主题向量回填**：加入 `documents.index_embedding` 列后，存量文档需要跑一次：
  - 预览：`.\scripts\rebuild_index_embeddings.ps1 -DryRun`
  - 回填（只处理缺失）：`.\scripts\rebuild_index_embeddings.ps1 -Yes`
  - 全量重算：`.\scripts\rebuild_index_embeddings.ps1 -All -Yes`
  - 回填失败不影响检索：`retrieve_by_query` 对未回填文档会自动降级为纯 KG 分数
- **rerank 调参思路**：
  - 如果发现"相关的文档被误过滤"，先把 `kg_index_rerank_min_score` 从 0.25 降到 0.15~0.20
  - 如果发现"无关文档还是上来"，调高 `kg_index_rerank_beta`（比如 0.5）并适当提升 `min_score`
  - 彻底回退：`kg_enable_index_rerank=False`

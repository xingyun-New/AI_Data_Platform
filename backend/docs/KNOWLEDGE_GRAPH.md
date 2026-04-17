# 知识图谱增强检索（GraphRAG）

## 概述

本平台在"脱敏 → 索引 → Dify 上传"流水线里，同步从每份文档抽取**实体+关系**沉淀为知识图谱，并暴露 `POST /api/graph/retrieve` 接口供 Dify 工作流在 RAG 前先做"图召回"，避免直接向量检索时漏掉相关文档。

## 数据模型

三张表构成双层图：

| 表 | 作用 |
| --- | --- |
| `kg_entities` | 归一化的实体节点（person / customer / project / product / org / contract / other），带 embedding |
| `kg_document_entities` | 边：Document --mentions / about / authored_by / belongs_to--> Entity |
| `kg_document_relations` | 边：Document ↔ Document（基于共享实体，无向；存储时 `src_id < dst_id`） |

## 构建流程

1. 文档通过 `POST /api/documents/{id}/generate-index` 或批量流水线时，`index_generator` 除了原有的索引元数据，还会**并行**调用 `graph_extract.txt` 抽取实体
2. `kg_service.save_graph()`：
   - 候选实体批量 embedding（DashScope `text-embedding-v3`）
   - **同类型内**按余弦相似度 ≥ `kg_entity_merge_threshold`（默认 0.88）合并已有实体；aliases 追加新字面形式；质心向量按加权均值更新
   - 写入 `kg_document_entities`
   - 用一条聚合 SQL 查出所有与新文档共享 ≥ `kg_min_shared_entities`（默认 2）实体的老文档，批量写 `kg_document_relations`；边数由 `kg_max_edges_per_doc`（默认 50）限流

## 相关配置（`backend/app/config.py`）

| 键 | 默认 | 作用 |
| --- | --- | --- |
| `kg_embedding_model` | `text-embedding-v3` | DashScope embedding 模型 |
| `kg_embedding_dim` | `1024` | 向量维度 |
| `kg_embedding_batch_size` | `10` | 单次 API 请求最大条数 |
| `kg_entity_merge_threshold` | `0.88` | 同类型实体合并的 cosine 阈值 |
| `kg_min_shared_entities` | `2` | 两文档共享实体数 ≥ N 才建边 |
| `kg_max_edges_per_doc` | `50` | 单文档最多保留的关系边数 |

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

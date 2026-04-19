# 实体与实体之间的关系是怎么体现的

> 本篇回答一个在开发过程中被反复问到的问题：在「图召回测试」页面的神经元关系图里，为什么两个实体之间看不到直接连线？系统是怎么表达 entity-to-entity 关联的？

## 结论

当前实现里，**实体 ↔ 实体没有显式的边**，实体之间的关系完全是「通过文档共现」间接体现的。

---

## 1. 数据层：根本就没有 entity-entity 表

见 [backend/app/models/knowledge_graph.py](../app/models/knowledge_graph.py)。核心表只有三张：

| 表 | 含义 |
| --- | --- |
| `kg_entities` | 实体节点本身 |
| `kg_document_entities` | **文档 → 实体** 的边 |
| `kg_document_relations` | **文档 → 文档** 的边（基于「共享实体数」推导出来） |

注意：**没有 `kg_entity_relations` 这种表**。`knowledge_graph.py` 顶部的注释也明确写着：

```
Three tables form the two-layer graph:
    kg_entities             — normalized entity nodes
    kg_document_entities    — edges: Document -> Entity
    kg_document_relations   — edges: Document -> Document (shared entities)
```

只做「两层图」是有意为之，见下文 §4 的 trade-off 说明。

---

## 2. 实体间关系在召回层是怎么被「感知」的

在 [backend/app/services/kg_service.py](../app/services/kg_service.py) 的 `retrieve_by_entities` 里，1-hop 扩展用的是 `DocumentRelation`，不是实体之间的边：

```python
rel_rows = db.query(
    DocumentRelation.src_doc_id,
    DocumentRelation.dst_doc_id,
    DocumentRelation.weight,
).filter(
    (DocumentRelation.src_doc_id.in_(direct_doc_ids))
    | (DocumentRelation.dst_doc_id.in_(direct_doc_ids))
).all()
```

也就是说：

1. 查询命中实体 A、B → 找到同时提到 A 或 B 的**直接文档** D1；
2. D1 通过 `DocumentRelation`（建索引时因为和 D2 共享过某些实体而存下的边）把 D2 捞进来；
3. D2 里提到的第三个实体 C，和 A、B 之间的「关联」其实只是「A/B 所在的文档 D1 与 C 所在的文档 D2 共享了别的实体」这种**间接关系**。

`DocumentRelation.shared_entities` 字段会存下到底是哪些实体把两个文档连起来的，但这是**边的元数据**，不是 entity-entity 本身的边。

---

## 3. 前端可视化层的体现方式

在 [frontend/src/components/kg/GraphRetrievalVisualization.tsx](../../frontend/src/components/kg/GraphRetrievalVisualization.tsx) 里，图上一共只画两种边：

- **Entity → Document**：来自每个 doc 的 `matched_entities`
- **Document ↔ Document**：来自后端新增的 `doc_relations`（1-hop 桥梁）

所以图上能**视觉推断**出的「实体间关系」只有一种路径：

```
实体A ── 实体B   ⇔   同时存在一条路径  A ── 文档D ── B
（两实体共用同一个文档节点作为中间枢纽）
```

两个实体之间如果没有共同文档，在当前图里就**无边可连**，视觉上会被力导向布局推开到不同区域。

---

## 4. 为什么要这么设计（trade-off）

**好处**：

- 实体抽取只要让 LLM 输出「这篇文档里有哪些实体」这种轻量产出，不需要 LLM 再去判断「实体 A 和实体 B 是什么关系」
- 抽取 prompt 简单、稳定性高、token 成本低
- 图谱规模受控：O(文档数 × 每文档实体数)，而不是 O(实体数²)

**代价**：

- 无法区分诸如 `张三 —上级是— 李四`、`A 项目 —属于— B 客户` 这种**有语义类型的关系**
- 所有 entity-entity 关联都退化成「同属一篇文档」，没有方向、没有谓词

---

## 5. 如果要显式展示「实体 ↔ 实体」的演进路径

按改动量从轻到重排列：

### 方案 1：前端派生（最轻量，不改 schema）

前端在召回结果上做「共现推导」——凡是两个实体出现在同一个文档的 `matched_entities` 里，就画一条实体 ↔ 实体的虚线，label 标注「共现于 X 篇文档」。

- 完全在 `GraphRetrievalVisualization` 里加一段派生逻辑即可
- 无需后端改动
- 缺点：关系没有语义、没有方向

### 方案 2：后端附带共现统计（中等改动）

给 `DocumentRelation.shared_entities`（见 [backend/app/models/knowledge_graph.py](../app/models/knowledge_graph.py) 第 112 行）一个专门的汇总查询，在 `/api/graph/retrieve` 响应里附带「本次涉及到的实体共现对 + 频次」。前端按频次加粗实体↔实体连线。

- 数据仍然源于「共现」，但可靠性和展示权重更合理
- 依然没有语义谓词

### 方案 3：新增 entity-entity 表（重量级）

新增 `kg_entity_relations` 表，LLM 抽取时直接让模型产出 `(subject, predicate, object)` 三元组（例如 `(张三, 负责, A项目)`）。这是知识图谱的标准做法，但：

- LLM 抽取 prompt 要重写；token 成本显著上升
- 需要解决谓词归一化（`负责 / 负责人 / 主管` 是否合并？）
- 需要处理抽取不稳定（同一文档多次抽取结果可能不一致）
- [KNOWLEDGE_GRAPH_ROADMAP.md](KNOWLEDGE_GRAPH_ROADMAP.md) 的 §4 已经把这类语义关系列为「不确定价值，待评估」档

---

## 相关文件索引

- 数据模型：[backend/app/models/knowledge_graph.py](../app/models/knowledge_graph.py)
- 召回服务：[backend/app/services/kg_service.py](../app/services/kg_service.py)
- 路由：[backend/app/api/routes/graph.py](../app/api/routes/graph.py)
- 前端可视化：[frontend/src/components/kg/GraphRetrievalVisualization.tsx](../../frontend/src/components/kg/GraphRetrievalVisualization.tsx)
- 路线图：[KNOWLEDGE_GRAPH_ROADMAP.md](KNOWLEDGE_GRAPH_ROADMAP.md)
- 架构总览：[KNOWLEDGE_GRAPH.md](KNOWLEDGE_GRAPH.md)

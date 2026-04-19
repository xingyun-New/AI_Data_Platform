import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Empty, Space, Tag, Typography } from 'antd';
import { Graph } from '@antv/g6';
import type { GraphData } from '@antv/g6';
import type { KgRetrieveDoc, KgRetrieveDocRelation } from '../../api/types';

interface MatchedEntity {
  id: number;
  name: string;
  type: string;
}

interface Props {
  matchedEntities: MatchedEntity[];
  documents: KgRetrieveDoc[];
  docRelations: KgRetrieveDocRelation[];
  onEntityClick?: (entityId: number) => void;
  height?: number;
}

// Hex palettes that roughly mirror the antd Tag colors used elsewhere.
const ENTITY_COLORS: Record<string, string> = {
  person: '#1677ff',
  customer: '#d48806',
  project: '#52c41a',
  product: '#722ed1',
  org: '#13c2c2',
  contract: '#eb2f96',
  other: '#8c8c8c',
};

const TYPE_LABEL: Record<string, string> = {
  person: '人物',
  customer: '客户',
  project: '项目',
  product: '产品',
  org: '组织',
  contract: '合同/订单',
  other: '其他',
};

const DIRECT_DOC_COLOR = '#ffd666';
const EXPAND_DOC_COLOR = '#595959';
const BG_COLOR = '#0f172a';

const LEGEND_ITEMS = [
  { color: DIRECT_DOC_COLOR, label: '直接命中文档' },
  { color: EXPAND_DOC_COLOR, label: '1-hop 扩展文档', dashed: true },
  { color: ENTITY_COLORS.product, label: '查询实体（按类型着色）' },
];

function entityNodeId(id: number) {
  return `ent:${id}`;
}
function docNodeId(id: number) {
  return `doc:${id}`;
}

export default function GraphRetrievalVisualization({
  matchedEntities,
  documents,
  docRelations,
  onEntityClick,
  height = 460,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const [hoverInfo, setHoverInfo] = useState<string | null>(null);

  const graphData = useMemo<GraphData>(() => {
    const nodes: GraphData['nodes'] = [];
    const edges: GraphData['edges'] = [];

    const entityIdSet = new Set(matchedEntities.map((e) => e.id));
    const entityById = new Map(matchedEntities.map((e) => [e.id, e]));

    // Entity nodes
    for (const ent of matchedEntities) {
      const fill = ENTITY_COLORS[ent.type] || ENTITY_COLORS.other;
      nodes!.push({
        id: entityNodeId(ent.id),
        data: {
          kind: 'entity',
          entityId: ent.id,
          entityType: ent.type,
          name: ent.name,
        },
        style: {
          size: 34,
          fill,
          stroke: '#ffffff',
          lineWidth: 2,
          labelText: ent.name,
          labelFill: '#e2e8f0',
          labelFontSize: 12,
          labelFontWeight: 600,
          labelPlacement: 'bottom',
          labelBackground: true,
          labelBackgroundFill: 'rgba(15,23,42,0.7)',
          labelBackgroundRadius: 4,
          labelPadding: [2, 6],
          shadowColor: fill,
          shadowBlur: 14,
        },
      });
    }

    // Document nodes
    const maxScore = Math.max(1, ...documents.map((d) => d.score));
    for (const doc of documents) {
      const isDirect = (doc.matched_entities?.length || 0) > 0;
      const fill = isDirect ? DIRECT_DOC_COLOR : EXPAND_DOC_COLOR;
      const size = 22 + Math.round((doc.score / maxScore) * 22);
      nodes!.push({
        id: docNodeId(doc.doc_id),
        data: {
          kind: 'document',
          docId: doc.doc_id,
          isDirect,
          score: doc.score,
          filename: doc.filename,
          department: doc.department,
        },
        style: {
          size,
          fill,
          stroke: isDirect ? '#fff7e6' : '#bfbfbf',
          lineWidth: isDirect ? 2 : 1,
          lineDash: isDirect ? undefined : [4, 3],
          labelText: doc.filename,
          labelFill: isDirect ? '#fffbe6' : '#d9d9d9',
          labelFontSize: 11,
          labelPlacement: 'bottom',
          labelBackground: true,
          labelBackgroundFill: 'rgba(15,23,42,0.7)',
          labelBackgroundRadius: 4,
          labelPadding: [2, 6],
          shadowColor: isDirect ? '#faad14' : 'transparent',
          shadowBlur: isDirect ? 16 : 0,
          opacity: isDirect ? 1 : 0.85,
        },
      });
    }

    // Entity -> Document edges (from each doc's matched_entities)
    for (const doc of documents) {
      for (const entId of doc.matched_entities || []) {
        if (!entityIdSet.has(entId)) continue;
        const intensity = Math.min(1, doc.score / maxScore);
        edges!.push({
          id: `e2d:${entId}:${doc.doc_id}`,
          source: entityNodeId(entId),
          target: docNodeId(doc.doc_id),
          data: { kind: 'entity-doc' },
          style: {
            lineWidth: 1.2 + intensity * 2.5,
            stroke: ENTITY_COLORS[entityById.get(entId)?.type || 'other'] || '#8c8c8c',
            strokeOpacity: 0.55 + intensity * 0.35,
            endArrow: false,
          },
        });
      }
    }

    // Document -> Document bridge edges (1-hop expansion)
    const docIdSet = new Set(documents.map((d) => d.doc_id));
    for (const rel of docRelations) {
      if (!docIdSet.has(rel.src_doc_id) || !docIdSet.has(rel.dst_doc_id)) continue;
      edges!.push({
        id: `d2d:${rel.src_doc_id}:${rel.dst_doc_id}`,
        source: docNodeId(rel.src_doc_id),
        target: docNodeId(rel.dst_doc_id),
        data: { kind: 'doc-doc', weight: rel.weight },
        style: {
          lineWidth: 1 + Math.min(3, rel.weight),
          stroke: '#bfbfbf',
          strokeOpacity: 0.6,
          lineDash: [5, 4],
          endArrow: false,
          labelText: `w=${rel.weight}`,
          labelFill: '#d9d9d9',
          labelFontSize: 10,
          labelBackground: true,
          labelBackgroundFill: 'rgba(15,23,42,0.6)',
          labelBackgroundRadius: 3,
          labelPadding: [1, 4],
        },
      });
    }

    return { nodes, edges };
  }, [matchedEntities, documents, docRelations]);

  useEffect(() => {
    if (!containerRef.current) return;
    if (!graphData.nodes || graphData.nodes.length === 0) return;

    const graph = new Graph({
      container: containerRef.current,
      data: graphData,
      autoFit: 'view',
      background: BG_COLOR,
      layout: {
        type: 'd3-force',
        collide: { radius: 50 },
        manyBody: { strength: -260 },
        link: { distance: 110 },
        preventOverlap: true,
      },
      behaviors: [
        'drag-canvas',
        'zoom-canvas',
        'drag-element',
        {
          type: 'hover-activate',
          degree: 1,
          state: 'active',
          inactiveState: 'inactive',
        },
      ],
      node: {
        state: {
          active: {
            lineWidth: 3,
            shadowBlur: 22,
          },
          inactive: {
            opacity: 0.2,
          },
        },
      },
      edge: {
        state: {
          active: {
            strokeOpacity: 1,
            lineWidth: 3,
          },
          inactive: {
            strokeOpacity: 0.1,
          },
        },
      },
    });

    graph.on('node:click', (evt: any) => {
      const id: string = evt.target?.id;
      if (!id) return;
      if (id.startsWith('ent:')) {
        const entityId = Number(id.slice(4));
        onEntityClick?.(entityId);
      }
    });

    graph.on('node:pointerenter', (evt: any) => {
      const id: string = evt.target?.id;
      if (!id) return;
      const nodeData = graph.getNodeData(id);
      const d: any = nodeData?.data || {};
      if (d.kind === 'entity') {
        setHoverInfo(`实体：${d.name}（${TYPE_LABEL[d.entityType] || d.entityType}）`);
      } else if (d.kind === 'document') {
        setHoverInfo(
          `文档：${d.filename}｜score ${d.score}｜${d.isDirect ? '直接命中' : '1-hop 扩展'}`,
        );
      }
    });
    graph.on('node:pointerleave', () => setHoverInfo(null));

    graph.render();
    graphRef.current = graph;

    const handleResize = () => {
      try {
        graph.resize();
      } catch {
        // ignore resize errors after destroy
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      try {
        graph.destroy();
      } catch {
        // ignore
      }
      graphRef.current = null;
    };
  }, [graphData, onEntityClick]);

  if (!graphData.nodes || graphData.nodes.length === 0) {
    return (
      <div
        style={{
          height,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: BG_COLOR,
          borderRadius: 8,
        }}
      >
        <Empty
          description={<span style={{ color: '#94a3b8' }}>暂无可视化的召回结果</span>}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      </div>
    );
  }

  return (
    <div style={{ position: 'relative', borderRadius: 8, overflow: 'hidden' }}>
      <div
        ref={containerRef}
        style={{ width: '100%', height, background: BG_COLOR }}
      />

      <div
        style={{
          position: 'absolute',
          left: 12,
          top: 12,
          background: 'rgba(15,23,42,0.75)',
          padding: '8px 10px',
          borderRadius: 6,
          color: '#e2e8f0',
          fontSize: 12,
          backdropFilter: 'blur(2px)',
        }}
      >
        <Space direction="vertical" size={2}>
          <Typography.Text style={{ color: '#94a3b8', fontSize: 11 }}>图例</Typography.Text>
          {LEGEND_ITEMS.map((item) => (
            <Space size={6} key={item.label}>
              {item.dashed ? (
                <span
                  style={{
                    display: 'inline-block',
                    width: 18,
                    height: 0,
                    borderTop: `2px dashed ${item.color}`,
                  }}
                />
              ) : (
                <span
                  style={{
                    display: 'inline-block',
                    width: 18,
                    height: 3,
                    background: item.color,
                    borderRadius: 2,
                  }}
                />
              )}
              <span style={{ color: '#e2e8f0' }}>{item.label}</span>
            </Space>
          ))}
          <Space size={4} wrap style={{ marginTop: 4 }}>
            {Object.keys(ENTITY_COLORS)
              .filter((t) => matchedEntities.some((e) => e.type === t))
              .map((t) => (
                <Tag
                  key={t}
                  color={ENTITY_COLORS[t]}
                  style={{ color: '#fff', border: 'none' }}
                >
                  {TYPE_LABEL[t] || t}
                </Tag>
              ))}
          </Space>
        </Space>
      </div>

      {hoverInfo && (
        <div
          style={{
            position: 'absolute',
            right: 12,
            top: 12,
            background: 'rgba(15,23,42,0.85)',
            padding: '6px 10px',
            borderRadius: 6,
            color: '#e2e8f0',
            fontSize: 12,
          }}
        >
          {hoverInfo}
        </div>
      )}

      <Typography.Text
        style={{
          position: 'absolute',
          left: 12,
          bottom: 8,
          color: '#94a3b8',
          fontSize: 11,
        }}
      >
        拖拽节点可手动布局 · 滚轮缩放 · 点击实体节点查看引用它的文档
      </Typography.Text>
    </div>
  );
}

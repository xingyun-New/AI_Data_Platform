import React, { useEffect, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Drawer,
  Empty,
  Input,
  List,
  message,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd';
import { ReloadOutlined, SearchOutlined, SendOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { graphApi } from '../api';
import type {
  KgEntity,
  KgEntityDocument,
  KgRetrieveDoc,
  KgStats,
} from '../api/types';

const ENTITY_TYPE_OPTIONS = [
  { value: 'person', label: '人物' },
  { value: 'customer', label: '客户' },
  { value: 'project', label: '项目' },
  { value: 'product', label: '产品' },
  { value: 'org', label: '组织' },
  { value: 'contract', label: '合同/订单' },
  { value: 'other', label: '其他' },
];

const TYPE_LABEL: Record<string, string> = Object.fromEntries(
  ENTITY_TYPE_OPTIONS.map((o) => [o.value, o.label]),
);

const TYPE_COLOR: Record<string, string> = {
  person: 'blue',
  customer: 'gold',
  project: 'green',
  product: 'purple',
  org: 'cyan',
  contract: 'magenta',
  other: 'default',
};

export default function KnowledgeGraphPage() {
  const [stats, setStats] = useState<KgStats | null>(null);
  const [entities, setEntities] = useState<KgEntity[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [typeFilter, setTypeFilter] = useState<string | undefined>();
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 });

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedEntity, setSelectedEntity] = useState<KgEntity | null>(null);
  const [entityDocs, setEntityDocs] = useState<KgEntityDocument[]>([]);

  const [rebuilding, setRebuilding] = useState(false);

  const [testQuery, setTestQuery] = useState('');
  const [testResult, setTestResult] = useState<{
    matched_entities: { id: number; name: string; type: string }[];
    documents: KgRetrieveDoc[];
  } | null>(null);
  const [testing, setTesting] = useState(false);

  const fetchStats = async () => {
    try {
      const { data } = await graphApi.stats();
      setStats(data);
    } catch {
      message.error('加载图谱统计失败');
    }
  };

  const fetchEntities = async (page = 1, size = 20) => {
    setLoading(true);
    try {
      const { data } = await graphApi.listEntities({
        q: keyword || undefined,
        entity_type: typeFilter,
        page,
        size,
      });
      setEntities(data.items);
      setPagination({ current: data.page, pageSize: data.size, total: data.total });
    } catch {
      message.error('加载实体列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
    fetchEntities();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openEntityDetail = async (entity: KgEntity) => {
    setSelectedEntity(entity);
    setDrawerOpen(true);
    try {
      const { data } = await graphApi.entityDocuments(entity.id);
      setEntityDocs(data.documents);
    } catch {
      message.error('加载实体详情失败');
      setEntityDocs([]);
    }
  };

  const handleRebuild = async () => {
    setRebuilding(true);
    try {
      const { data } = await graphApi.rebuild({ only_missing: true });
      message.success(
        `回填完成：共 ${data.total}，成功 ${data.success}，失败 ${data.failed}`,
      );
      fetchStats();
      fetchEntities(pagination.current, pagination.pageSize);
    } catch (err: any) {
      message.error(`回填失败：${err?.message || '未知错误'}`);
    } finally {
      setRebuilding(false);
    }
  };

  const handleTestRetrieve = async () => {
    if (!testQuery.trim()) return;
    setTesting(true);
    try {
      const { data } = await graphApi.retrieve({ query: testQuery.trim(), top_k: 10 });
      setTestResult({
        matched_entities: data.matched_entities,
        documents: data.documents,
      });
    } catch (err: any) {
      message.error(`检索失败：${err?.message || '未知错误'}`);
    } finally {
      setTesting(false);
    }
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    {
      title: '类型',
      dataIndex: 'entity_type',
      width: 110,
      render: (t: string) => (
        <Tag color={TYPE_COLOR[t] || 'default'}>{TYPE_LABEL[t] || t}</Tag>
      ),
    },
    {
      title: '实体名',
      dataIndex: 'name',
      render: (name: string, row: KgEntity) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{name}</Typography.Text>
          {row.aliases.length > 0 && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              别名：{row.aliases.join('、')}
            </Typography.Text>
          )}
        </Space>
      ),
    },
    { title: '被提及次数', dataIndex: 'mention_count', width: 120 },
    {
      title: '操作',
      width: 120,
      render: (_: unknown, row: KgEntity) => (
        <Button size="small" onClick={() => openEntityDetail(row)}>
          查看引用
        </Button>
      ),
    },
  ];

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Row gutter={16}>
        <Col span={6}>
          <Card>
            <Statistic title="实体总数" value={stats?.entity_count ?? 0} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="文档-实体 边"
              value={stats?.document_entity_count ?? 0}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="文档-文档 关系"
              value={stats?.document_relation_count ?? 0}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Space direction="vertical" size={0} style={{ width: '100%' }}>
              <Typography.Text type="secondary">按类型分布</Typography.Text>
              <Space wrap size={[4, 4]}>
                {stats?.entities_by_type &&
                  Object.entries(stats.entities_by_type).map(([t, n]) => (
                    <Tag color={TYPE_COLOR[t] || 'default'} key={t}>
                      {TYPE_LABEL[t] || t}: {n}
                    </Tag>
                  ))}
                {!stats?.entities_by_type && <Typography.Text>-</Typography.Text>}
              </Space>
            </Space>
          </Card>
        </Col>
      </Row>

      <Card
        title="图召回测试"
        extra={
          <Typography.Text type="secondary">
            模拟 Dify 工作流对 /api/graph/retrieve 的调用
          </Typography.Text>
        }
      >
        <Space.Compact style={{ width: '100%' }}>
          <Input
            placeholder="输入问题，例如：A项目最近进展如何？"
            value={testQuery}
            onChange={(e) => setTestQuery(e.target.value)}
            onPressEnter={handleTestRetrieve}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={testing}
            onClick={handleTestRetrieve}
          >
            检索
          </Button>
        </Space.Compact>

        {testResult && (
          <div style={{ marginTop: 16 }}>
            <Typography.Text strong>命中实体：</Typography.Text>
            {testResult.matched_entities.length === 0 ? (
              <Typography.Text type="secondary">（未命中任何实体）</Typography.Text>
            ) : (
              <Space wrap style={{ marginLeft: 8 }}>
                {testResult.matched_entities.map((e) => (
                  <Tag color={TYPE_COLOR[e.type] || 'default'} key={e.id}>
                    {e.name}（{TYPE_LABEL[e.type] || e.type}）
                  </Tag>
                ))}
              </Space>
            )}
            <List
              style={{ marginTop: 12 }}
              header={<Typography.Text strong>召回文档（Top {testResult.documents.length}）</Typography.Text>}
              dataSource={testResult.documents}
              renderItem={(d) => (
                <List.Item>
                  <Space direction="vertical" size={0} style={{ width: '100%' }}>
                    <Space>
                      <Typography.Text strong>{d.filename}</Typography.Text>
                      <Tag>{d.department || '未分部门'}</Tag>
                      <Tag color="blue">score: {d.score}</Tag>
                    </Space>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      命中实体：{d.matched_entities.join(', ') || '（仅通过 1-hop 扩展召回）'}
                    </Typography.Text>
                  </Space>
                </List.Item>
              )}
              locale={{ emptyText: <Empty description="无召回结果" /> }}
            />
          </div>
        )}
      </Card>

      <Card
        title="实体列表"
        extra={
          <Space>
            <Input
              placeholder="名称/别名模糊"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onPressEnter={() => fetchEntities(1, pagination.pageSize)}
              prefix={<SearchOutlined />}
              allowClear
              style={{ width: 220 }}
            />
            <Select
              placeholder="类型"
              allowClear
              value={typeFilter}
              onChange={(v) => setTypeFilter(v)}
              options={ENTITY_TYPE_OPTIONS}
              style={{ width: 140 }}
            />
            <Button
              icon={<SearchOutlined />}
              onClick={() => fetchEntities(1, pagination.pageSize)}
            >
              查询
            </Button>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => {
                setKeyword('');
                setTypeFilter(undefined);
                fetchEntities(1, pagination.pageSize);
              }}
            >
              重置
            </Button>
            <Popconfirm
              title="回填存量文档的图数据？"
              description="仅处理尚未建过图的 indexed/uploaded 文档，会产生 LLM 调用费用。"
              onConfirm={handleRebuild}
            >
              <Button
                type="primary"
                icon={<ThunderboltOutlined />}
                loading={rebuilding}
              >
                回填图数据
              </Button>
            </Popconfirm>
          </Space>
        }
      >
        <Table
          rowKey="id"
          loading={loading}
          dataSource={entities}
          columns={columns}
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: pagination.total,
            onChange: (page, size) => fetchEntities(page, size),
            showSizeChanger: true,
          }}
        />
      </Card>

      <Drawer
        title={
          selectedEntity ? (
            <Space>
              <Tag color={TYPE_COLOR[selectedEntity.entity_type] || 'default'}>
                {TYPE_LABEL[selectedEntity.entity_type] || selectedEntity.entity_type}
              </Tag>
              <span>{selectedEntity.name}</span>
            </Space>
          ) : '实体详情'
        }
        placement="right"
        width={560}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        {selectedEntity && (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            {selectedEntity.aliases.length > 0 && (
              <div>
                <Typography.Text type="secondary">别名：</Typography.Text>
                <Space wrap>
                  {selectedEntity.aliases.map((a) => (
                    <Tag key={a}>{a}</Tag>
                  ))}
                </Space>
              </div>
            )}
            <List
              header={
                <Typography.Text strong>
                  引用该实体的文档（{entityDocs.length}）
                </Typography.Text>
              }
              dataSource={entityDocs}
              renderItem={(d) => (
                <List.Item>
                  <Space direction="vertical" size={0}>
                    <Typography.Text strong>{d.filename}</Typography.Text>
                    <Space size={4}>
                      <Tag>{d.department || '未分部门'}</Tag>
                      <Tag color="geekblue">{d.relation_type}</Tag>
                      <Tag color="default">{d.status}</Tag>
                    </Space>
                  </Space>
                </List.Item>
              )}
              locale={{ emptyText: <Empty description="暂无引用文档" /> }}
            />
          </Space>
        )}
      </Drawer>
    </Space>
  );
}

import React, { useEffect, useState } from 'react';
import {
  Button,
  Card,
  Drawer,
  Empty,
  Input,
  message,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from 'antd';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ApartmentOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  EyeOutlined,
  FileProtectOutlined,
  NodeIndexOutlined,
  ReloadOutlined,
  SearchOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import type { DocumentItem, KnowledgeBase } from '../api';
import { docApi, graphApi, settingsApi } from '../api';
import type { KgDocumentGraph, KgGraphNode } from '../api/types';

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  raw: { color: 'default', label: '未处理' },
  desensitized: { color: 'blue', label: '已脱敏' },
  indexed: { color: 'green', label: '已索引' },
  uploaded: { color: 'purple', label: '已上传Dify' },
  error: { color: 'red', label: '错误' },
};

export default function DocumentListPage() {
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);

  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 });

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerTitle, setDrawerTitle] = useState('');
  const [rawContent, setRawContent] = useState('');
  const [redactedContent, setRedactedContent] = useState('');

  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKbId, setSelectedKbId] = useState<string>('');
  const [defaultKbId, setDefaultKbId] = useState<string>('');

  const [graphDrawerOpen, setGraphDrawerOpen] = useState(false);
  const [graphDrawerTitle, setGraphDrawerTitle] = useState('');
  const [graphData, setGraphData] = useState<KgDocumentGraph | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);

  const fetchDocs = async (page = 1, size = 20) => {
    setLoading(true);
    try {
      const { data } = await docApi.list({
        keyword: keyword || undefined,
        status: statusFilter,
        page,
        size,
      });
      setDocs(data.items);
      setPagination({ current: data.page, pageSize: data.size, total: data.total });
    } catch {
      message.error('加载文档列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchDocs(); fetchKnowledgeBases(); }, []);

  const fetchKnowledgeBases = async () => {
    try {
      const { data } = await settingsApi.getKnowledgeBases();
      setKnowledgeBases(data.knowledge_bases || []);
      if (data.default_id) {
        setDefaultKbId(data.default_id);
        if (data.knowledge_bases?.length > 0) {
          setSelectedKbId(data.default_id);
        }
      }
    } catch {
      // Silently fail - knowledge bases are optional for display
    }
  };

  const handleTableChange = (pag: any) => {
    fetchDocs(pag.current, pag.pageSize);
  };

  const handleSearch = () => {
    fetchDocs(1, pagination.pageSize);
  };

  const handleView = async (doc: DocumentItem) => {
    try {
      const { data: raw } = await docApi.get(doc.id);
      setRawContent(raw.content);
      try {
        const { data: redacted } = await docApi.getRedacted(doc.id);
        setRedactedContent(redacted.content);
      } catch {
        setRedactedContent('（脱敏版本尚未生成）');
      }
      setDrawerTitle(doc.filename);
      setDrawerOpen(true);
    } catch {
      message.error('加载文档内容失败');
    }
  };

  const handleUpload = async (file: File) => {
    const dept = localStorage.getItem('department') || '';
    try {
      await docApi.upload(file, dept, selectedKbId);
      message.success(`${file.name} 上传成功`);
      fetchDocs(pagination.current, pagination.pageSize);
    } catch {
      message.error(`${file.name} 上传失败`);
    }
    return false;
  };

  const handleDesensitize = async (doc: DocumentItem) => {
    try {
      message.loading({ content: '正在脱敏处理...', key: `desensitize-${doc.id}`, duration: 0 });
      const { data } = await docApi.desensitize(doc.id);
      message.success({ content: `脱敏完成，修改 ${data.report?.total_changes ?? 0} 处`, key: `desensitize-${doc.id}` });
      fetchDocs(pagination.current, pagination.pageSize);
    } catch {
      message.error({ content: '脱敏处理失败', key: `desensitize-${doc.id}` });
    }
  };

  const handleIndex = async (doc: DocumentItem) => {
    try {
      message.loading({ content: '正在生成索引...', key: `index-${doc.id}`, duration: 0 });
      await docApi.generateIndex(doc.id);
      message.success({ content: '索引生成完成', key: `index-${doc.id}` });
      fetchDocs(pagination.current, pagination.pageSize);
    } catch {
      message.error({ content: '索引生成失败', key: `index-${doc.id}` });
    }
  };

  const handleUploadToDify = async (doc: DocumentItem) => {
    try {
      message.loading({ content: '正在上传完整版与脱敏版到 Dify 知识库...', key: `dify-${doc.id}`, duration: 0 });
      const { data } = await docApi.uploadToDify(doc.id, selectedKbId || undefined);
      const count = data.uploaded?.length ?? 0;
      message.success({ content: `已上传 ${count} 个文件到 Dify 知识库`, key: `dify-${doc.id}` });
      fetchDocs(pagination.current, pagination.pageSize);
    } catch {
      message.error({ content: '上传 Dify 失败', key: `dify-${doc.id}` });
    }
  };

  const handleViewGraph = async (doc: DocumentItem) => {
    setGraphDrawerTitle(doc.filename);
    setGraphDrawerOpen(true);
    setGraphLoading(true);
    setGraphData(null);
    try {
      const { data } = await graphApi.documentGraph(doc.id);
      setGraphData(data);
    } catch {
      message.error('加载图谱失败');
    } finally {
      setGraphLoading(false);
    }
  };

  const handleDelete = async (doc: DocumentItem) => {
    try {
      await docApi.delete(doc.id);
      message.success(`${doc.filename} 已删除`);
      fetchDocs(pagination.current, pagination.pageSize);
    } catch {
      message.error('删除失败');
    }
  };

  const handleBatchDesensitize = async () => {
    const rawDocs = docs.filter((d) => selectedRowKeys.includes(d.id) && d.status === 'raw');
    if (rawDocs.length === 0) {
      message.warning('请选择未处理的文档进行批量脱敏');
      return;
    }
    message.loading({ content: `正在批量脱敏 ${rawDocs.length} 个文档...`, key: 'batch-desensitize', duration: 0 });
    let success = 0;
    let fail = 0;
    for (const doc of rawDocs) {
      try {
        await docApi.desensitize(doc.id);
        success++;
      } catch {
        fail++;
      }
    }
    message.success({
      content: `批量脱敏完成：成功 ${success} 个，失败 ${fail} 个`,
      key: 'batch-desensitize',
    });
    setSelectedRowKeys([]);
    fetchDocs(pagination.current, pagination.pageSize);
  };

  const handleBatchIndex = async () => {
    const rawDocs = docs.filter((d) => selectedRowKeys.includes(d.id) && d.status === 'desensitized');
    if (rawDocs.length === 0) {
      message.warning('请选择已脱敏的文档进行批量索引');
      return;
    }
    message.loading({ content: `正在批量生成索引 ${rawDocs.length} 个文档...`, key: 'batch-index', duration: 0 });
    let success = 0;
    let fail = 0;
    for (const doc of rawDocs) {
      try {
        await docApi.generateIndex(doc.id);
        success++;
      } catch {
        fail++;
      }
    }
    message.success({
      content: `批量索引完成：成功 ${success} 个，失败 ${fail} 个`,
      key: 'batch-index',
    });
    setSelectedRowKeys([]);
    fetchDocs(pagination.current, pagination.pageSize);
  };

  const handleBatchDelete = async () => {
    const toDelete = docs.filter((d) => selectedRowKeys.includes(d.id));
    if (toDelete.length === 0) {
      message.warning('请选择要删除的文档');
      return;
    }
    message.loading({ content: `正在删除 ${toDelete.length} 个文档...`, key: 'batch-delete', duration: 0 });
    let success = 0;
    let fail = 0;
    for (const doc of toDelete) {
      try {
        await docApi.delete(doc.id);
        success++;
      } catch {
        fail++;
      }
    }
    message.success({
      content: `批量删除完成：成功 ${success} 个，失败 ${fail} 个`,
      key: 'batch-delete',
    });
    setSelectedRowKeys([]);
    fetchDocs(pagination.current, pagination.pageSize);
  };

  const rowSelection = {
    selectedRowKeys,
    onChange: (keys: React.Key[]) => setSelectedRowKeys(keys),
  };

  const batchActions = (
    <Space>
      {selectedRowKeys.length > 0 && (
        <>
          <Button size="small" icon={<FileProtectOutlined />} onClick={handleBatchDesensitize}>
            批量脱敏 ({selectedRowKeys.length})
          </Button>
          <Button size="small" icon={<NodeIndexOutlined />} onClick={handleBatchIndex}>
            批量索引 ({selectedRowKeys.length})
          </Button>
          <Popconfirm
            title="确定批量删除？"
            description="删除后将无法恢复。"
            onConfirm={handleBatchDelete}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>
              批量删除 ({selectedRowKeys.length})
            </Button>
          </Popconfirm>
        </>
      )}
    </Space>
  );


  const columns = [
    { title: '文件名', dataIndex: 'filename', key: 'filename', ellipsis: true },
    {
      title: '部门/课', key: 'department', width: 140,
      render: (_: unknown, record: DocumentItem) => {
        const parts = [record.department, record.section].filter(Boolean);
        return parts.join('/') || '-';
      },
    },
    { title: '上传者', dataIndex: 'uploaded_by', key: 'uploaded_by', width: 100 },
    {
      title: '知识库', key: 'knowledge_base', width: 130,
      render: (_: unknown, record: DocumentItem) => {
        if (!record.knowledge_base_id) return <span style={{ color: '#999' }}>-</span>;
        const kb = knowledgeBases.find(k => k.id === record.knowledge_base_id);
        return kb ? <Tag color="blue">{kb.name}</Tag> : <span style={{ color: '#999' }}>{record.knowledge_base_id}</span>;
      },
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (s: string) => {
        const m = STATUS_MAP[s] || { color: 'default', label: s };
        return <Tag color={m.color}>{m.label}</Tag>;
      },
    },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 180 },
    {
      title: '操作', key: 'action', width: 260,
      render: (_: unknown, record: DocumentItem) => (
        <Space size="small">
          <Tooltip title="查看内容"><Button size="small" icon={<EyeOutlined />} onClick={() => handleView(record)} /></Tooltip>
          <Tooltip title="AI 脱敏"><Button size="small" icon={<FileProtectOutlined />} onClick={() => handleDesensitize(record)} /></Tooltip>
          <Tooltip title="生成索引"><Button size="small" icon={<NodeIndexOutlined />} onClick={() => handleIndex(record)} /></Tooltip>
          <Tooltip title="上传到 Dify 知识库">
            <Button
              size="small"
              icon={<CloudUploadOutlined />}
              disabled={record.status !== 'indexed' && record.status !== 'uploaded'}
              onClick={() => handleUploadToDify(record)}
            />
          </Tooltip>
          <Tooltip title="查看知识图谱">
            <Button
              size="small"
              icon={<ApartmentOutlined />}
              onClick={() => handleViewGraph(record)}
            />
          </Tooltip>
          <Popconfirm
            title="确定删除？"
            description="删除后将无法恢复，包括原版、脱敏版和索引文件。"
            onConfirm={() => handleDelete(record)}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Tooltip title="删除文档"><Button size="small" danger icon={<DeleteOutlined />} /></Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Card
        title="文档列表"
        extra={
          <Space>
            <Select
              placeholder="选择目标知识库"
              style={{ width: 180 }}
              value={selectedKbId || undefined}
              onChange={(val) => setSelectedKbId(val || '')}
              options={knowledgeBases.map(kb => ({
                value: kb.id,
                label: kb.name + (kb.id === defaultKbId ? ' (默认)' : ''),
              }))}
              allowClear
            />
            <Upload
              accept=".md"
              showUploadList={false}
              multiple
              beforeUpload={(file) => { handleUpload(file as unknown as File); return false; }}
            >
              <Button type="primary" icon={<UploadOutlined />}>上传 MD 文档</Button>
            </Upload>
            <Input placeholder="搜索文件名" prefix={<SearchOutlined />} value={keyword} onChange={(e) => setKeyword(e.target.value)} onPressEnter={handleSearch} style={{ width: 200 }} allowClear />
            <Select placeholder="状态筛选" allowClear style={{ width: 120 }} value={statusFilter} onChange={setStatusFilter} options={Object.entries(STATUS_MAP).map(([k, v]) => ({ value: k, label: v.label }))} />
            <Button icon={<ReloadOutlined />} onClick={() => fetchDocs(pagination.current, pagination.pageSize)}>刷新</Button>
          </Space>
        }
      >
        {batchActions}
        <Table
          dataSource={docs}
          columns={columns}
          rowKey="id"
          loading={loading}
          size="middle"
          rowSelection={rowSelection}
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: pagination.total,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条记录`,
          }}
          onChange={handleTableChange}
          locale={{ emptyText: <Empty description="暂无文档数据" image={Empty.PRESENTED_IMAGE_SIMPLE}><Button type="primary" icon={<UploadOutlined />}>上传第一个文档</Button></Empty> }}
        />
      </Card>

      <Drawer
        title={`知识图谱 · ${graphDrawerTitle}`}
        width={640}
        open={graphDrawerOpen}
        onClose={() => setGraphDrawerOpen(false)}
      >
        {graphLoading && <Typography.Text type="secondary">正在加载…</Typography.Text>}
        {!graphLoading && graphData && <DocumentGraphPanel data={graphData} />}
        {!graphLoading && !graphData && <Empty description="该文档尚未构建图谱" />}
      </Drawer>

      <Drawer title={drawerTitle} size="80%" open={drawerOpen} onClose={() => setDrawerOpen(false)}>
        <div style={{ display: 'flex', gap: 16 }}>
          <div style={{ flex: 1 }}>
            <Typography.Title level={5}>原版</Typography.Title>
            <div style={{ background: '#fafafa', padding: 16, borderRadius: 8, maxHeight: '70vh', overflow: 'auto' }}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{rawContent}</ReactMarkdown>
            </div>
          </div>
          <div style={{ flex: 1 }}>
            <Typography.Title level={5}>脱敏版</Typography.Title>
            <div style={{ background: '#f6ffed', padding: 16, borderRadius: 8, maxHeight: '70vh', overflow: 'auto' }}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{redactedContent}</ReactMarkdown>
            </div>
          </div>
        </div>
      </Drawer>
    </>
  );
}

const ENTITY_TYPE_LABEL: Record<string, string> = {
  person: '人物',
  customer: '客户',
  project: '项目',
  product: '产品',
  org: '组织',
  contract: '合同',
  other: '其他',
};

const ENTITY_TYPE_COLOR: Record<string, string> = {
  person: 'blue',
  customer: 'gold',
  project: 'green',
  product: 'purple',
  org: 'cyan',
  contract: 'magenta',
  other: 'default',
};

function DocumentGraphPanel({ data }: { data: KgDocumentGraph }) {
  const rootNode = data.nodes.find((n) => n.type === 'document' && n.is_root);
  const entityNodes = data.nodes.filter((n) => n.type === 'entity');
  const relatedDocs = data.nodes.filter((n) => n.type === 'document' && !n.is_root);

  if (!rootNode) {
    return <Empty description="未找到文档节点" />;
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <section>
        <Typography.Title level={5}>本文档提及的实体（{entityNodes.length}）</Typography.Title>
        {entityNodes.length === 0 ? (
          <Typography.Text type="secondary">（未抽取到实体）</Typography.Text>
        ) : (
          <Space wrap>
            {entityNodes.map((n: KgGraphNode) => (
              <Tag
                color={ENTITY_TYPE_COLOR[n.entity_type || ''] || 'default'}
                key={n.id}
              >
                {n.label}
                <Typography.Text
                  type="secondary"
                  style={{ marginLeft: 4, fontSize: 11 }}
                >
                  ({ENTITY_TYPE_LABEL[n.entity_type || ''] || n.entity_type})
                </Typography.Text>
              </Tag>
            ))}
          </Space>
        )}
      </section>

      <section>
        <Typography.Title level={5}>相关文档（{relatedDocs.length}）</Typography.Title>
        {relatedDocs.length === 0 ? (
          <Typography.Text type="secondary">
            （暂无共享实体数达到阈值的相关文档）
          </Typography.Text>
        ) : (
          <div>
            {relatedDocs.map((n: KgGraphNode) => {
              const edge = data.edges.find(
                (e) =>
                  (e.source === n.id && e.target.startsWith('doc:')) ||
                  (e.target === n.id && e.source.startsWith('doc:')),
              );
              return (
                <div
                  key={n.id}
                  style={{
                    padding: '8px 12px',
                    borderBottom: '1px solid #f0f0f0',
                  }}
                >
                  <Space>
                    <Typography.Text strong>{n.label}</Typography.Text>
                    {n.department && <Tag>{n.department}</Tag>}
                    {edge?.type && (
                      <Tag color="geekblue">{edge.type}</Tag>
                    )}
                    {edge?.weight !== undefined && (
                      <Tag color="orange">共享实体 {edge.weight}</Tag>
                    )}
                  </Space>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </Space>
  );
}

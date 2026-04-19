import React, { useEffect, useState } from 'react';
import {
  Button,
  Card,
  Descriptions,
  Input,
  message,
  Modal,
  Select,
  Space,
  Table,
  Tag,
} from 'antd';
import {
  PlayCircleOutlined,
  ReloadOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons';
import type { BatchFileLogItem, BatchSummary, KnowledgeBase } from '../api';
import { batchApi, settingsApi } from '../api';

const STATUS_COLOR: Record<string, string> = {
  running: 'processing',
  completed: 'success',
  failed: 'error',
};

export default function BatchMonitorPage() {
  const [history, setHistory] = useState<BatchSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<Record<string, unknown> | null>(null);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 });

  const [logModalOpen, setLogModalOpen] = useState(false);
  const [logs, setLogs] = useState<BatchFileLogItem[]>([]);
  const [logBatchId, setLogBatchId] = useState('');

  const [batchDept, setBatchDept] = useState('');
  const [batchKbId, setBatchKbId] = useState<string | undefined>(undefined);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [defaultKbId, setDefaultKbId] = useState('');

  const fetchHistory = async (page = 1, size = 20) => {
    setLoading(true);
    try {
      const { data } = await batchApi.history({ page, size });
      setHistory(data.items);
      setPagination({ current: data.page, pageSize: data.size, total: data.total });
    } catch {
      message.error('加载 Batch 历史失败');
    } finally {
      setLoading(false);
    }
  };

  const handleTableChange = (pag: any) => {
    fetchHistory(pag.current, pag.pageSize);
  };

  const checkStatus = async () => {
    const { data } = await batchApi.status();
    setRunning(data.is_running);
  };

  const fetchKnowledgeBases = async () => {
    try {
      const { data } = await settingsApi.getKnowledgeBases();
      setKnowledgeBases(data.knowledge_bases || []);
      if (data.default_id) setDefaultKbId(data.default_id);
    } catch { /* optional */ }
  };

  useEffect(() => { fetchHistory(); checkStatus(); fetchKnowledgeBases(); }, []);

  const handleRun = async () => {
    setRunning(true);
    setRunResult(null);
    message.loading({ content: 'Batch 执行中...', key: 'batch', duration: 0 });
    try {
      const params: Record<string, string> = {};
      if (batchDept) params.department = batchDept;
      if (batchKbId) params.knowledge_base_id = batchKbId;
      const { data } = await batchApi.run(Object.keys(params).length ? params : undefined);
      setRunResult(data);
      message.success({ content: `Batch 完成: ${data.success ?? 0} 成功, ${data.fail ?? 0} 失败`, key: 'batch' });
      fetchHistory();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error({ content: detail || 'Batch 执行失败', key: 'batch' });
    } finally {
      setRunning(false);
    }
  };

  const viewLogs = async (batchId: string) => {
    setLogBatchId(batchId);
    try {
      const { data } = await batchApi.logs(batchId);
      setLogs(data);
      setLogModalOpen(true);
    } catch {
      message.error('加载日志失败');
    }
  };

  const columns = [
    { title: 'Batch ID', dataIndex: 'batch_id', key: 'batch_id', width: 220 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (s: string) => <Tag color={STATUS_COLOR[s] || 'default'}>{s}</Tag>,
    },
    { title: '总文件', dataIndex: 'total_files', key: 'total_files', width: 80 },
    { title: '成功', dataIndex: 'success_count', key: 'success_count', width: 80 },
    { title: '失败', dataIndex: 'fail_count', key: 'fail_count', width: 80 },
    { title: '开始时间', dataIndex: 'started_at', key: 'started_at', width: 180 },
    { title: '结束时间', dataIndex: 'finished_at', key: 'finished_at', width: 180 },
    {
      title: '操作', key: 'action', width: 80,
      render: (_: unknown, r: BatchSummary) => (
        <Button size="small" icon={<UnorderedListOutlined />} onClick={() => viewLogs(r.batch_id)}>日志</Button>
      ),
    },
  ];

  const logColumns = [
    { title: '文档 ID', dataIndex: 'document_id', key: 'document_id', width: 80 },
    { title: '步骤', dataIndex: 'step', key: 'step', width: 100 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => <Tag color={s === 'success' ? 'green' : s === 'failed' ? 'red' : 'default'}>{s}</Tag>,
    },
    { title: '耗时 (ms)', dataIndex: 'duration_ms', key: 'duration_ms', width: 100, render: (v: number) => v.toFixed(0) },
    { title: '错误信息', dataIndex: 'error_message', key: 'error_message', ellipsis: true },
  ];

  return (
    <>
      <Card
        title="Batch 监控"
        extra={
          <Space>
            <Input
              placeholder="部门，如 CH70/CH73"
              value={batchDept}
              onChange={(e) => setBatchDept(e.target.value)}
              style={{ width: 160 }}
              allowClear
            />
            <Select
              placeholder="选择知识库"
              value={batchKbId}
              onChange={setBatchKbId}
              style={{ width: 180 }}
              allowClear
              options={knowledgeBases.map(kb => ({
                value: kb.id,
                label: kb.name + (kb.id === defaultKbId ? ' (默认)' : ''),
              }))}
            />
            <Button type="primary" icon={<PlayCircleOutlined />} loading={running} onClick={handleRun}>
              {running ? '执行中...' : '执行 Batch'}
            </Button>
            <Button icon={<ReloadOutlined />} onClick={() => fetchHistory()}>刷新</Button>
          </Space>
        }
      >
        {runResult && (
          <Descriptions size="small" bordered style={{ marginBottom: 16 }}>
            <Descriptions.Item label="Batch ID">{String(runResult.batch_id ?? '')}</Descriptions.Item>
            <Descriptions.Item label="状态">{String(runResult.status ?? '')}</Descriptions.Item>
            <Descriptions.Item label="总文件">{String(runResult.total ?? '')}</Descriptions.Item>
            <Descriptions.Item label="成功">{String(runResult.success ?? '')}</Descriptions.Item>
            <Descriptions.Item label="失败">{String(runResult.fail ?? '')}</Descriptions.Item>
          </Descriptions>
        )}
        <Table
          dataSource={history}
          columns={columns}
          rowKey="batch_id"
          loading={loading}
          size="middle"
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: pagination.total,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条记录`,
          }}
          onChange={handleTableChange}
        />
      </Card>

      <Modal title={`日志 - ${logBatchId}`} open={logModalOpen} onCancel={() => setLogModalOpen(false)} footer={null} width={900}>
        <Table dataSource={logs} columns={logColumns} rowKey="id" size="small" pagination={false} />
      </Modal>
    </>
  );
}

import React, { useEffect, useState } from 'react';
import {
  Button,
  Card,
  Form,
  Input,
  message,
  Radio,
  Space,
  Table,
  Tabs,
  Tag,
  Modal,
  Typography,
  Switch,
  Tooltip,
} from 'antd';
import {
  SaveOutlined,
  ReloadOutlined,
  FolderOpenOutlined,
  SettingOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  CloudServerOutlined,
} from '@ant-design/icons';
import type { SettingsGroup, KnowledgeBase } from '../api';
import { settingsApi } from '../api';

const { Title, Text, Paragraph } = Typography;

interface ResolvedPaths {
  md_raw_dir: string;
  md_redacted_dir: string;
  index_dir: string;
}

export default function SettingsPage() {
  const [form] = Form.useForm();
  const [kbForm] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [pathMode, setPathMode] = useState<'relative' | 'absolute'>('relative');
  const [resolvedPaths, setResolvedPaths] = useState<ResolvedPaths | null>(null);

  // Knowledge base state
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [defaultKbId, setDefaultKbId] = useState('');
  const [kbModalOpen, setKbModalOpen] = useState(false);
  const [editingKb, setEditingKb] = useState<KnowledgeBase | null>(null);

  const fetchSettings = async () => {
    setLoading(true);
    try {
      const { data } = await settingsApi.getAll();
      const dify = data.dify || {};
      const pathData = data.path || {};
      const currentPathMode = (pathData.path_mode || 'relative') as 'relative' | 'absolute';

      setPathMode(currentPathMode);

      form.setFieldsValue({
        dify_api_key: dify.dify_api_key || '',
        dify_base_url: dify.dify_base_url || '',
        dify_dataset_id: dify.dify_dataset_id || '',
        md_raw_dir: pathData.md_raw_dir || '../data/raw',
        md_redacted_dir: pathData.md_redacted_dir || '../data/redacted',
        index_dir: pathData.index_dir || '../data/index',
      });

      if (currentPathMode === 'absolute') {
        const paths: ResolvedPaths = {
          md_raw_dir: pathData.md_raw_dir_abs || pathData.md_raw_dir || '',
          md_redacted_dir: pathData.md_redacted_dir_abs || pathData.md_redacted_dir || '',
          index_dir: pathData.index_dir_abs || pathData.index_dir || '',
        };
        if (paths.md_raw_dir) form.setFieldValue('md_raw_dir', paths.md_raw_dir);
        if (paths.md_redacted_dir) form.setFieldValue('md_redacted_dir', paths.md_redacted_dir);
        if (paths.index_dir) form.setFieldValue('index_dir', paths.index_dir);
      }

      resolvePathsIfNeeded(pathData.md_raw_dir || '../data/raw', pathData.md_redacted_dir || '../data/redacted', pathData.index_dir || '../data/index', currentPathMode);
    } catch {
      message.error('加载配置失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchKnowledgeBases = async () => {
    try {
      const { data } = await settingsApi.getKnowledgeBases();
      setKnowledgeBases(data.knowledge_bases || []);
      setDefaultKbId(data.default_id || '');
    } catch {
      message.error('加载知识库列表失败');
    }
  };

  const resolvePathsIfNeeded = async (raw: string, redacted: string, index: string, mode: 'relative' | 'absolute') => {
    if (mode === 'absolute') {
      try {
        const [r1, r2, r3] = await Promise.all([
          settingsApi.resolvePath(raw),
          settingsApi.resolvePath(redacted),
          settingsApi.resolvePath(index),
        ]);
        setResolvedPaths({
          md_raw_dir: r1.data.absolute_path,
          md_redacted_dir: r2.data.absolute_path,
          index_dir: r3.data.absolute_path,
        });
      } catch {
        setResolvedPaths(null);
      }
    } else {
      setResolvedPaths(null);
    }
  };

  const handlePathModeChange = async (e: any) => {
    const newMode = e.target.value as 'relative' | 'absolute';
    setPathMode(newMode);

    const values = form.getFieldsValue();
    if (newMode === 'absolute') {
      const rawPath = values.md_raw_dir || '../data/raw';
      const redactedPath = values.md_redacted_dir || '../data/redacted';
      const indexPath = values.index_dir || '../data/index';
      await resolvePathsIfNeeded(rawPath, redactedPath, indexPath, 'absolute');
    } else {
      const defaults: Record<string, string> = {
        md_raw_dir: '../data/raw',
        md_redacted_dir: '../data/redacted',
        index_dir: '../data/index',
      };
      form.setFieldsValue(defaults);
      setResolvedPaths(null);
    }
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);

      await settingsApi.updateAll({
        dify: {
          dify_api_key: values.dify_api_key,
          dify_base_url: values.dify_base_url,
          dify_dataset_id: values.dify_dataset_id,
        },
        path: {
          md_raw_dir: values.md_raw_dir,
          md_redacted_dir: values.md_redacted_dir,
          index_dir: values.index_dir,
          path_mode: pathMode,
        },
      });

      message.success('配置已保存');
      fetchSettings();
    } catch {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    form.resetFields();
    setPathMode('relative');
    setResolvedPaths(null);
    fetchSettings();
    message.info('已重置为上次保存的配置');
  };

  // Knowledge base handlers
  const handleSetDefault = async (kbId: string) => {
    try {
      await settingsApi.saveKnowledgeBases({
        knowledge_bases: knowledgeBases,
        default_id: kbId,
      });
      setDefaultKbId(kbId);
      message.success('已设置默认知识库');
    } catch {
      message.error('设置默认知识库失败');
    }
  };

  const handleDeleteKb = async (kbId: string) => {
    if (kbId === defaultKbId && knowledgeBases.length > 1) {
      message.warning('请先将其他知识库设为默认后再删除');
      return;
    }
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除此知识库吗？',
      onOk: async () => {
        const updated = knowledgeBases.filter(kb => kb.id !== kbId);
        const newDefault = defaultKbId === kbId ? (updated[0]?.id || '') : defaultKbId;
        try {
          await settingsApi.saveKnowledgeBases({
            knowledge_bases: updated,
            default_id: newDefault,
          });
          setKnowledgeBases(updated);
          setDefaultKbId(newDefault);
          message.success('已删除');
        } catch {
          message.error('删除失败');
        }
      },
    });
  };

  const handleOpenKbModal = (kb?: KnowledgeBase) => {
    if (kb) {
      setEditingKb(kb);
      kbForm.setFieldsValue(kb);
    } else {
      setEditingKb(null);
      kbForm.resetFields();
    }
    setKbModalOpen(true);
  };

  const handleSaveKb = async () => {
    try {
      const values = await kbForm.validateFields();
      const newKb: KnowledgeBase = {
        id: editingKb?.id || `kb_${Date.now()}`,
        name: values.name,
        api_key: values.api_key,
        base_url: values.base_url,
        dataset_id: values.dataset_id,
      };

      let updated: KnowledgeBase[];
      if (editingKb) {
        updated = knowledgeBases.map(kb => kb.id === editingKb.id ? newKb : kb);
      } else {
        updated = [...knowledgeBases, newKb];
      }

      await settingsApi.saveKnowledgeBases({
        knowledge_bases: updated,
        default_id: defaultKbId || newKb.id,
      });

      setKnowledgeBases(updated);
      if (!defaultKbId && updated.length === 1) {
        setDefaultKbId(newKb.id);
      }
      setKbModalOpen(false);
      message.success(editingKb ? '知识库已更新' : '知识库已添加');
    } catch {
      // validation error
    }
  };

  useEffect(() => {
    fetchSettings();
    fetchKnowledgeBases();
  }, []);

  // Knowledge bases table columns
  const kbColumns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
    },
    {
      title: 'API Key',
      dataIndex: 'api_key',
      key: 'api_key',
      width: 200,
      render: (text: string) => text ? `${text.slice(0, 8)}****` : '-',
    },
    {
      title: 'Base URL',
      dataIndex: 'base_url',
      key: 'base_url',
      width: 220,
    },
    {
      title: 'Dataset ID',
      dataIndex: 'dataset_id',
      key: 'dataset_id',
      width: 280,
    },
    {
      title: '默认',
      key: 'is_default',
      width: 60,
      render: (_: unknown, record: KnowledgeBase) => (
        record.id === defaultKbId ? <Tag color="blue">默认</Tag> : <Switch size="small" onClick={() => handleSetDefault(record.id)} />
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: unknown, record: KnowledgeBase) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => handleOpenKbModal(record)} />
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDeleteKb(record.id)} />
        </Space>
      ),
    },
  ];

  const tabItems = [
    {
      key: 'knowledge-base',
      label: <><CloudServerOutlined /> 知识库管理</>,
      children: (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => handleOpenKbModal()}>
              新增知识库
            </Button>
          </div>
          <Table
            dataSource={knowledgeBases}
            columns={kbColumns}
            rowKey="id"
            loading={loading}
            size="middle"
            pagination={false}
            rowClassName={(record: KnowledgeBase) => record.id === defaultKbId ? 'default-kb-row' : ''}
          />
          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
            可配置多个知识库，每个知识库独立设置 API Key、Base URL 和 Dataset ID。
            文档上传时默认使用标记为"默认"的知识库，也可在上传时手动选择。
          </Paragraph>
        </div>
      ),
    },
    {
      key: 'data-dir',
      label: <><FolderOpenOutlined /> 数据目录配置</>,
      children: (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Form form={form} layout="vertical" disabled={loading}>
            <div style={{ marginBottom: 24, padding: 16, background: '#fafafa', borderRadius: 8 }}>
              <Text strong>路径模式：</Text>
              <Radio.Group value={pathMode} onChange={handlePathModeChange} style={{ marginTop: 8 }}>
                <Radio.Button value="relative">相对路径</Radio.Button>
                <Radio.Button value="absolute">绝对路径</Radio.Button>
              </Radio.Group>
              <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
                {pathMode === 'relative'
                  ? '路径相对于 backend/ 目录，例如 ../data/raw'
                  : '使用完整绝对路径，例如 D:\\data\\raw'}
              </Paragraph>
            </div>

            <Form.Item
              name="md_raw_dir"
              label="原始文件目录"
              tooltip="存放原始 Markdown 文件的目录"
              rules={[{ required: true, message: '请输入原始文件目录' }]}
            >
              <Input placeholder={pathMode === 'relative' ? '../data/raw' : 'D:\\data\\raw'} />
            </Form.Item>
            {pathMode === 'relative' && resolvedPaths && (
              <div style={{ marginTop: -16, marginBottom: 16, padding: '8px 12px', background: '#e6f4ff', borderRadius: 4, fontSize: 12 }}>
                <Text type="secondary">解析为: {resolvedPaths.md_raw_dir}</Text>
              </div>
            )}

            <Form.Item
              name="md_redacted_dir"
              label="脱敏文件目录"
              tooltip="存放脱敏后 Markdown 文件的目录"
              rules={[{ required: true, message: '请输入脱敏文件目录' }]}
            >
              <Input placeholder={pathMode === 'relative' ? '../data/redacted' : 'D:\\data\\redacted'} />
            </Form.Item>
            {pathMode === 'relative' && resolvedPaths && (
              <div style={{ marginTop: -16, marginBottom: 16, padding: '8px 12px', background: '#e6f4ff', borderRadius: 4, fontSize: 12 }}>
                <Text type="secondary">解析为: {resolvedPaths.md_redacted_dir}</Text>
              </div>
            )}

            <Form.Item
              name="index_dir"
              label="索引文件目录"
              tooltip="存放索引文件的目录"
              rules={[{ required: true, message: '请输入索引文件目录' }]}
            >
              <Input placeholder={pathMode === 'relative' ? '../data/index' : 'D:\\data\\index'} />
            </Form.Item>
            {pathMode === 'relative' && resolvedPaths && (
              <div style={{ marginTop: -16, marginBottom: 16, padding: '8px 12px', background: '#e6f4ff', borderRadius: 4, fontSize: 12 }}>
                <Text type="secondary">解析为: {resolvedPaths.index_dir}</Text>
              </div>
            )}
          </Form>

          <Space>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              onClick={handleSave}
              loading={saving}
              size="large"
            >
              保存配置
            </Button>
            <Button
              icon={<ReloadOutlined />}
              onClick={handleReset}
              size="large"
            >
              重置
            </Button>
          </Space>
        </div>
      ),
    },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <Card>
        <Title level={4}>
          <SettingOutlined style={{ marginRight: 8 }} />
          系统配置
        </Title>
        <Paragraph type="secondary">
          管理知识库连接信息和数据目录路径。配置将保存到数据库中，修改后立即生效。
        </Paragraph>
        <Tabs items={tabItems} />
      </Card>

      <Modal
        title={editingKb ? '编辑知识库' : '新增知识库'}
        open={kbModalOpen}
        onOk={handleSaveKb}
        onCancel={() => setKbModalOpen(false)}
        okText="保存"
        width={560}
      >
        <Form form={kbForm} layout="vertical">
          <Form.Item name="name" label="知识库名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="例如：HR 知识库、产品知识库" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key" rules={[{ required: true, message: '请输入 API Key' }]}>
            <Input.Password placeholder="dataset-xxx" />
          </Form.Item>
          <Form.Item name="base_url" label="Base URL" rules={[{ required: true, message: '请输入 Base URL' }]}>
            <Input placeholder="http://172.24.122.176/v1" />
          </Form.Item>
          <Form.Item name="dataset_id" label="Dataset ID" rules={[{ required: true, message: '请输入 Dataset ID' }]}>
            <Input placeholder="741aa2ef-b710-46f3-8933-289c1ca668bd" />
          </Form.Item>
        </Form>
      </Modal>

      <style>{`
        .default-kb-row { background-color: #e6f7ff; }
      `}</style>
    </div>
  );
}

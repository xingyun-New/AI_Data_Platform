import React, { useEffect, useState } from 'react';
import {
  Button,
  Card,
  Form,
  Input,
  message,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  InputNumber,
} from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import type { IndexRuleItem, PromptFile, RuleItem } from '../api';
import { indexRuleApi, promptApi, ruleApi } from '../api';

const DESENSITIZE_RULE_TYPES = [
  { value: 'remove', label: '移除', color: 'red' },
  { value: 'replace', label: '替换', color: 'orange' },
  { value: 'summarize', label: '概括', color: 'blue' },
];

const INDEX_RULE_TYPES = [
  { value: 'share', label: '共享', color: 'blue' },
  { value: 'access', label: '权限', color: 'green' },
  { value: 'classify', label: '分类', color: 'purple' },
];

export default function RuleManagePage() {
  /* ───── 脱敏规则状态 ───── */
  const [rules, setRules] = useState<RuleItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<RuleItem | null>(null);
  const [form] = Form.useForm();

  /* ───── 索引规则状态 ───── */
  const [indexRules, setIndexRules] = useState<IndexRuleItem[]>([]);
  const [indexLoading, setIndexLoading] = useState(false);
  const [indexModalOpen, setIndexModalOpen] = useState(false);
  const [editingIndexRule, setEditingIndexRule] = useState<IndexRuleItem | null>(null);
  const [indexForm] = Form.useForm();

  /* ───── 提示词状态 ───── */
  const [prompts, setPrompts] = useState<PromptFile[]>([]);
  const [editingPrompt, setEditingPrompt] = useState<PromptFile | null>(null);
  const [promptContent, setPromptContent] = useState('');

  const department = localStorage.getItem('department') || '';

  /* ========== 脱敏规则 CRUD ========== */

  const fetchRules = async () => {
    setLoading(true);
    try {
      const { data } = await ruleApi.list({ department });
      setRules(data.items);
    } catch {
      message.error('加载规则失败');
    } finally {
      setLoading(false);
    }
  };

  const handleSaveRule = async () => {
    try {
      const values = await form.validateFields();
      if (editingRule) {
        await ruleApi.update(editingRule.id, values);
        message.success('规则已更新');
      } else {
        await ruleApi.create({ ...values, department: values.department || department });
        message.success('规则已创建');
      }
      setModalOpen(false);
      form.resetFields();
      setEditingRule(null);
      fetchRules();
    } catch {
      // validation error
    }
  };

  const handleDelete = async (id: number) => {
    await ruleApi.delete(id);
    message.success('规则已删除');
    fetchRules();
  };

  const handleToggle = async (rule: RuleItem, checked: boolean) => {
    await ruleApi.update(rule.id, { is_active: checked });
    fetchRules();
  };

  const openEdit = (rule: RuleItem) => {
    setEditingRule(rule);
    form.setFieldsValue(rule);
    setModalOpen(true);
  };

  const openCreate = () => {
    setEditingRule(null);
    form.resetFields();
    form.setFieldsValue({ department, rule_type: 'replace', priority: 0, is_active: true });
    setModalOpen(true);
  };

  /* ========== 索引规则 CRUD ========== */

  const fetchIndexRules = async () => {
    setIndexLoading(true);
    try {
      const { data } = await indexRuleApi.list({ department });
      setIndexRules(data.items);
    } catch {
      message.error('加载索引规则失败');
    } finally {
      setIndexLoading(false);
    }
  };

  const handleSaveIndexRule = async () => {
    try {
      const values = await indexForm.validateFields();
      const payload = {
        ...values,
        department: values.department || department,
        target_departments: values.target_departments || [],
      };
      if (editingIndexRule) {
        await indexRuleApi.update(editingIndexRule.id, payload);
        message.success('索引规则已更新');
      } else {
        await indexRuleApi.create(payload);
        message.success('索引规则已创建');
      }
      setIndexModalOpen(false);
      indexForm.resetFields();
      setEditingIndexRule(null);
      fetchIndexRules();
    } catch {
      // validation error
    }
  };

  const handleDeleteIndexRule = async (id: number) => {
    await indexRuleApi.delete(id);
    message.success('索引规则已删除');
    fetchIndexRules();
  };

  const handleToggleIndexRule = async (rule: IndexRuleItem, checked: boolean) => {
    await indexRuleApi.update(rule.id, { is_active: checked });
    fetchIndexRules();
  };

  const openIndexEdit = (rule: IndexRuleItem) => {
    setEditingIndexRule(rule);
    indexForm.setFieldsValue(rule);
    setIndexModalOpen(true);
  };

  const openIndexCreate = () => {
    setEditingIndexRule(null);
    indexForm.resetFields();
    indexForm.setFieldsValue({ department, rule_type: 'share', target_departments: [], priority: 0, is_active: true });
    setIndexModalOpen(true);
  };

  /* ========== 提示词 ========== */

  const fetchPrompts = async () => {
    try {
      const { data } = await promptApi.list();
      setPrompts(data);
    } catch {
      message.error('加载提示词失败');
    }
  };

  const handleSavePrompt = async () => {
    if (!editingPrompt) return;
    try {
      await promptApi.update(editingPrompt.filename, promptContent);
      message.success('提示词已保存');
      fetchPrompts();
    } catch {
      message.error('保存失败');
    }
  };

  /* ========== 初始加载 ========== */

  useEffect(() => {
    fetchRules();
    fetchIndexRules();
    fetchPrompts();
  }, []);

  /* ========== 脱敏规则表格列 ========== */

  const ruleColumns = [
    { title: '规则名称', dataIndex: 'rule_name', key: 'rule_name' },
    { title: '部门', dataIndex: 'department', key: 'department', width: 120 },
    {
      title: '类型', dataIndex: 'rule_type', key: 'rule_type', width: 90,
      render: (t: string) => {
        const m = DESENSITIZE_RULE_TYPES.find((r) => r.value === t);
        return <Tag color={m?.color}>{m?.label ?? t}</Tag>;
      },
    },
    { title: '描述', dataIndex: 'rule_description', key: 'rule_description', ellipsis: true },
    { title: '优先级', dataIndex: 'priority', key: 'priority', width: 80 },
    {
      title: '启用', key: 'is_active', width: 70,
      render: (_: unknown, r: RuleItem) => <Switch size="small" checked={r.is_active} onChange={(c) => handleToggle(r, c)} />,
    },
    {
      title: '操作', key: 'action', width: 100,
      render: (_: unknown, r: RuleItem) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)} />
          <Popconfirm title="确定删除？" onConfirm={() => handleDelete(r.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  /* ========== 索引规则表格列 ========== */

  const indexRuleColumns = [
    { title: '规则名称', dataIndex: 'rule_name', key: 'rule_name' },
    { title: '部门', dataIndex: 'department', key: 'department', width: 120 },
    {
      title: '规则类型', dataIndex: 'rule_type', key: 'rule_type', width: 90,
      render: (t: string) => {
        const m = INDEX_RULE_TYPES.find((r) => r.value === t);
        return <Tag color={m?.color}>{m?.label ?? t}</Tag>;
      },
    },
    { title: '描述', dataIndex: 'rule_description', key: 'rule_description', ellipsis: true },
    {
      title: '目标部门', dataIndex: 'target_departments', key: 'target_departments', width: 200,
      render: (depts: string[]) =>
        depts && depts.length > 0
          ? depts.map((d) => <Tag key={d} color="cyan">{d}</Tag>)
          : <span style={{ color: '#999' }}>-</span>,
    },
    { title: '优先级', dataIndex: 'priority', key: 'priority', width: 80 },
    {
      title: '启用', key: 'is_active', width: 70,
      render: (_: unknown, r: IndexRuleItem) => <Switch size="small" checked={r.is_active} onChange={(c) => handleToggleIndexRule(r, c)} />,
    },
    {
      title: '操作', key: 'action', width: 100,
      render: (_: unknown, r: IndexRuleItem) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => openIndexEdit(r)} />
          <Popconfirm title="确定删除？" onConfirm={() => handleDeleteIndexRule(r.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  /* ========== 渲染 ========== */

  return (
    <>
      <Card>
        <Tabs
          items={[
            {
              key: 'rules',
              label: '脱敏规则',
              children: (
                <>
                  <div style={{ marginBottom: 16 }}>
                    <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增规则</Button>
                  </div>
                  <Table dataSource={rules} columns={ruleColumns} rowKey="id" loading={loading} size="middle" pagination={false} />
                </>
              ),
            },
            {
              key: 'index-rules',
              label: '索引规则',
              children: (
                <>
                  <div style={{ marginBottom: 16 }}>
                    <Button type="primary" icon={<PlusOutlined />} onClick={openIndexCreate}>新增索引规则</Button>
                  </div>
                  <Table dataSource={indexRules} columns={indexRuleColumns} rowKey="id" loading={indexLoading} size="middle" pagination={false} />
                </>
              ),
            },
            {
              key: 'prompts',
              label: '提示词编辑',
              children: (
                <div style={{ display: 'flex', gap: 16 }}>
                  <div style={{ width: 200 }}>
                    {prompts.map((p) => (
                      <Card
                        key={p.filename}
                        size="small"
                        hoverable
                        style={{ marginBottom: 8, border: editingPrompt?.filename === p.filename ? '2px solid #1677ff' : undefined }}
                        onClick={() => { setEditingPrompt(p); setPromptContent(p.content); }}
                      >
                        {p.filename}
                      </Card>
                    ))}
                  </div>
                  <div style={{ flex: 1 }}>
                    {editingPrompt ? (
                      <>
                        <Input.TextArea
                          value={promptContent}
                          onChange={(e) => setPromptContent(e.target.value)}
                          rows={20}
                          style={{ fontFamily: 'monospace', fontSize: 13 }}
                        />
                        <Button type="primary" style={{ marginTop: 12 }} onClick={handleSavePrompt}>保存提示词</Button>
                      </>
                    ) : (
                      <div style={{ color: '#999', paddingTop: 40, textAlign: 'center' }}>请选择左侧提示词文件</div>
                    )}
                  </div>
                </div>
              ),
            },
          ]}
        />
      </Card>

      {/* 脱敏规则 Modal */}
      <Modal
        title={editingRule ? '编辑规则' : '新增规则'}
        open={modalOpen}
        onOk={handleSaveRule}
        onCancel={() => { setModalOpen(false); setEditingRule(null); }}
        okText="保存"
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="department" label="适用部门" rules={[{ required: true }]}>
            <Input placeholder="例如 Sales, PE, R&D" />
          </Form.Item>
          <Form.Item name="rule_name" label="规则名称" rules={[{ required: true }]}>
            <Input placeholder="例如：隐藏客户联系方式" />
          </Form.Item>
          <Form.Item name="rule_description" label="规则描述（自然语言）" rules={[{ required: true }]}>
            <Input.TextArea rows={3} placeholder="用自然语言描述脱敏要求，例如：将所有客户的手机号码和邮箱地址替换为占位符" />
          </Form.Item>
          <Space>
            <Form.Item name="rule_type" label="脱敏类型">
              <Select style={{ width: 120 }} options={DESENSITIZE_RULE_TYPES} />
            </Form.Item>
            <Form.Item name="priority" label="优先级">
              <InputNumber min={0} max={100} />
            </Form.Item>
            <Form.Item name="is_active" label="启用" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      {/* 索引规则 Modal */}
      <Modal
        title={editingIndexRule ? '编辑索引规则' : '新增索引规则'}
        open={indexModalOpen}
        onOk={handleSaveIndexRule}
        onCancel={() => { setIndexModalOpen(false); setEditingIndexRule(null); }}
        okText="保存"
        width={640}
      >
        <Form form={indexForm} layout="vertical">
          <Form.Item name="department" label="适用部门" rules={[{ required: true, message: '请输入部门' }]}>
            <Input placeholder="例如 Sales, PE, R&D" />
          </Form.Item>
          <Form.Item name="rule_name" label="规则名称" rules={[{ required: true, message: '请输入规则名称' }]}>
            <Input placeholder="例如：产品需求类文档共享给 PE" />
          </Form.Item>
          <Form.Item name="rule_description" label="规则描述（自然语言）" rules={[{ required: true, message: '请输入规则描述' }]}>
            <Input.TextArea
              rows={3}
              placeholder="用自然语言描述索引/共享规则，例如：当文档内容涉及产品需求、功能规划时，默认共享给 PE 技术部门"
            />
          </Form.Item>
          <Space align="start" size={16}>
            <Form.Item name="rule_type" label="规则类型" rules={[{ required: true }]}>
              <Select style={{ width: 120 }} options={INDEX_RULE_TYPES} />
            </Form.Item>
            <Form.Item name="priority" label="优先级">
              <InputNumber min={0} max={100} />
            </Form.Item>
            <Form.Item name="is_active" label="启用" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>
          <Form.Item noStyle shouldUpdate={(prev, cur) => prev.rule_type !== cur.rule_type}>
            {({ getFieldValue }) =>
              getFieldValue('rule_type') === 'share' ? (
                <Form.Item
                  name="target_departments"
                  label="目标共享部门"
                  tooltip="输入部门代码后按回车添加，可添加多个"
                >
                  <Select
                    mode="tags"
                    style={{ width: '100%' }}
                    placeholder="输入部门代码后按回车，如 PE、R&D、Finance"
                    tokenSeparators={[',', '，']}
                  />
                </Form.Item>
              ) : null
            }
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

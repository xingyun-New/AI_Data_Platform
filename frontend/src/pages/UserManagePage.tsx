import React, { useEffect, useMemo, useState } from 'react';
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
  Tooltip,
  Typography,
} from 'antd';
import { DeleteOutlined, PlusOutlined, ReloadOutlined, TeamOutlined } from '@ant-design/icons';
import { deptApi, userApi } from '../api';
import type { DepartmentOut, RoleName, UserOut } from '../api';
import { ROLE_LABELS } from '../utils/permissions';

const ROLE_OPTIONS: { value: RoleName; label: string; color: string }[] = [
  { value: 'SYS_ADMIN', label: ROLE_LABELS.SYS_ADMIN, color: 'red' },
  { value: 'BE_CROSS', label: ROLE_LABELS.BE_CROSS, color: 'gold' },
  { value: 'DEPT_PIC', label: ROLE_LABELS.DEPT_PIC, color: 'blue' },
  { value: 'MEMBER', label: ROLE_LABELS.MEMBER, color: 'default' },
];

export default function UserManagePage() {
  const [activeTab, setActiveTab] = useState<'users' | 'departments'>('users');

  return (
    <Card
      title={
        <Space>
          <TeamOutlined />
          用户与角色管理
        </Space>
      }
    >
      <Tabs
        activeKey={activeTab}
        onChange={(k) => setActiveTab(k as 'users' | 'departments')}
        items={[
          { key: 'users', label: '用户列表', children: <UserTabPanel /> },
          { key: 'departments', label: '部门管理', children: <DepartmentTabPanel /> },
        ]}
      />
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------

function UserTabPanel() {
  const [users, setUsers] = useState<UserOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [departments, setDepartments] = useState<DepartmentOut[]>([]);

  const [grantOpen, setGrantOpen] = useState(false);
  const [grantUser, setGrantUser] = useState<UserOut | null>(null);
  const [grantForm] = Form.useForm<{ role: RoleName; department_id?: number }>();

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const { data } = await userApi.list({ keyword: keyword || undefined });
      setUsers(data);
    } catch {
      message.error('加载用户列表失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchDepartments = async () => {
    try {
      const { data } = await deptApi.list();
      setDepartments(data);
    } catch {
      // optional
    }
  };

  useEffect(() => {
    fetchUsers();
    fetchDepartments();
  }, []);

  const deptById = useMemo(() => {
    const map = new Map<number, DepartmentOut>();
    departments.forEach((d) => map.set(d.id, d));
    return map;
  }, [departments]);

  const handleToggleActive = async (user: UserOut, next: boolean) => {
    try {
      await userApi.update(user.id, { is_active: next });
      message.success(next ? '已启用' : '已禁用');
      fetchUsers();
    } catch {
      message.error('操作失败');
    }
  };

  const openGrant = (user: UserOut) => {
    setGrantUser(user);
    grantForm.resetFields();
    setGrantOpen(true);
  };

  const handleGrant = async () => {
    if (!grantUser) return;
    const values = await grantForm.validateFields();
    try {
      await userApi.grantRole(grantUser.id, {
        role: values.role,
        department_id: values.role === 'DEPT_PIC' ? values.department_id : null,
      });
      message.success('角色授予成功');
      setGrantOpen(false);
      fetchUsers();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '授予失败');
    }
  };

  const handleRevoke = async (user: UserOut, bindingId: number) => {
    try {
      await userApi.revokeRole(user.id, bindingId);
      message.success('已撤销');
      fetchUsers();
    } catch {
      message.error('撤销失败');
    }
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 64 },
    { title: '用户名', dataIndex: 'username', width: 140 },
    { title: '显示名', dataIndex: 'display_name', width: 160 },
    {
      title: '部门/课',
      key: 'dept',
      width: 160,
      render: (_: unknown, record: UserOut) =>
        [record.department, record.section].filter(Boolean).join('/') || '-',
    },
    {
      title: '角色',
      key: 'roles',
      render: (_: unknown, record: UserOut) => (
        <Space wrap size={[4, 4]}>
          {record.roles.length === 0 && <Typography.Text type="secondary">（无）</Typography.Text>}
          {record.roles.map((r) => {
            const opt = ROLE_OPTIONS.find((o) => o.value === r.role);
            const label = opt?.label || r.role;
            const suffix = r.department_code ? `·${r.department_code}` : '';
            return (
              <Popconfirm
                key={r.id}
                title="撤销该角色？"
                onConfirm={() => handleRevoke(record, r.id)}
                okText="撤销"
                cancelText="取消"
              >
                <Tooltip title="点击撤销">
                  <Tag color={opt?.color || 'default'} style={{ cursor: 'pointer' }}>
                    {label}
                    {suffix}
                  </Tag>
                </Tooltip>
              </Popconfirm>
            );
          })}
        </Space>
      ),
    },
    {
      title: '状态',
      key: 'is_active',
      width: 100,
      render: (_: unknown, record: UserOut) => (
        <Switch
          checked={record.is_active}
          onChange={(v) => handleToggleActive(record, v)}
          checkedChildren="启用"
          unCheckedChildren="禁用"
        />
      ),
    },
    {
      title: '最近登录',
      dataIndex: 'last_login_at',
      width: 180,
      render: (v: string | null) => v || '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 140,
      render: (_: unknown, record: UserOut) => (
        <Button size="small" icon={<PlusOutlined />} onClick={() => openGrant(record)}>
          授予角色
        </Button>
      ),
    },
  ];

  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="搜索用户名 / 显示名"
          allowClear
          style={{ width: 260 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onSearch={fetchUsers}
        />
        <Button icon={<ReloadOutlined />} onClick={fetchUsers}>
          刷新
        </Button>
      </Space>
      <Table rowKey="id" dataSource={users} columns={columns} loading={loading} size="middle" />

      <Modal
        title={grantUser ? `为 ${grantUser.display_name || grantUser.username} 授予角色` : '授予角色'}
        open={grantOpen}
        onCancel={() => setGrantOpen(false)}
        onOk={handleGrant}
        okText="授予"
        cancelText="取消"
      >
        <Form form={grantForm} layout="vertical">
          <Form.Item name="role" label="角色" rules={[{ required: true, message: '请选择角色' }]}>
            <Select
              placeholder="选择角色"
              options={ROLE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
          </Form.Item>
          <Form.Item
            noStyle
            shouldUpdate={(prev, next) => prev.role !== next.role}
          >
            {({ getFieldValue }) =>
              getFieldValue('role') === 'DEPT_PIC' ? (
                <Form.Item
                  name="department_id"
                  label="负责的部门"
                  rules={[{ required: true, message: '请选择部门' }]}
                >
                  <Select
                    placeholder="选择部门"
                    options={departments.map((d) => ({
                      value: d.id,
                      label: `${d.code}${d.name && d.name !== d.code ? ' · ' + d.name : ''}`,
                    }))}
                    showSearch
                    optionFilterProp="label"
                  />
                </Form.Item>
              ) : null
            }
          </Form.Item>
          <Typography.Text type="secondary">
            同一个用户可以拥有多个角色。例如「A 部门 PIC + BE 跨部门管理员」。
          </Typography.Text>
        </Form>
      </Modal>
    </>
  );
}

// ---------------------------------------------------------------------------
// Departments
// ---------------------------------------------------------------------------

function DepartmentTabPanel() {
  const [departments, setDepartments] = useState<DepartmentOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm<{ code: string; name?: string }>();

  const fetchDepartments = async () => {
    setLoading(true);
    try {
      const { data } = await deptApi.list();
      setDepartments(data);
    } catch {
      message.error('加载部门失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDepartments();
  }, []);

  const handleToggle = async (dept: DepartmentOut, next: boolean) => {
    try {
      await deptApi.update(dept.id, { is_active: next });
      fetchDepartments();
    } catch {
      message.error('更新失败');
    }
  };

  const handleCreate = async () => {
    const values = await form.validateFields();
    try {
      await deptApi.create({ code: values.code, name: values.name || values.code });
      message.success('部门已创建');
      setCreateOpen(false);
      form.resetFields();
      fetchDepartments();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '创建失败');
    }
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 64 },
    { title: '代码', dataIndex: 'code', width: 160 },
    { title: '名称', dataIndex: 'name' },
    {
      title: '启用',
      key: 'is_active',
      width: 100,
      render: (_: unknown, record: DepartmentOut) => (
        <Switch checked={record.is_active} onChange={(v) => handleToggle(record, v)} />
      ),
    },
  ];

  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          新建部门
        </Button>
        <Button icon={<ReloadOutlined />} onClick={fetchDepartments}>
          刷新
        </Button>
      </Space>
      <Table rowKey="id" dataSource={departments} columns={columns} loading={loading} size="middle" />

      <Modal
        title="新建部门"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreate}
        okText="创建"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="code"
            label="部门代码"
            rules={[{ required: true, message: '请输入部门代码' }]}
            extra="建议使用短代码，例如 BE / PE / RD / Sales"
          >
            <Input placeholder="BE" />
          </Form.Item>
          <Form.Item name="name" label="部门名称">
            <Input placeholder="留空则与代码相同" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

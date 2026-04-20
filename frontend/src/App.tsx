import React from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { ConfigProvider, Layout, Menu, Typography, Button, theme } from 'antd';
import {
  ApartmentOutlined,
  FileTextOutlined,
  LogoutOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  TeamOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import zhCN from 'antd/locale/zh_CN';

import LoginPage from './pages/LoginPage';
import DocumentListPage from './pages/DocumentListPage';
import RuleManagePage from './pages/RuleManagePage';
import BatchMonitorPage from './pages/BatchMonitorPage';
import SettingsPage from './pages/SettingsPage';
import KnowledgeGraphPage from './pages/KnowledgeGraphPage';
import UserManagePage from './pages/UserManagePage';
import {
  canManageRules,
  canManageSettings,
  canManageUsers,
  canUseBatch,
  loadRoles,
  ROLE_LABELS,
} from './utils/permissions';

const { Sider, Content, Header } = Layout;

type MenuItem = { key: string; icon: React.ReactNode; label: string; visible: () => boolean };

const MENU_ITEMS: MenuItem[] = [
  { key: '/documents', icon: <FileTextOutlined />, label: '文档管理', visible: () => true },
  { key: '/rules', icon: <SafetyCertificateOutlined />, label: '规则管理', visible: canManageRules },
  { key: '/batch', icon: <ThunderboltOutlined />, label: 'Batch 监控', visible: canUseBatch },
  { key: '/knowledge-graph', icon: <ApartmentOutlined />, label: '知识图谱', visible: () => true },
  { key: '/users', icon: <TeamOutlined />, label: '用户管理', visible: canManageUsers },
  { key: '/settings', icon: <SettingOutlined />, label: '系统设置', visible: canManageSettings },
];

function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const displayName = localStorage.getItem('display_name') || localStorage.getItem('username') || '';
  const department = localStorage.getItem('department') || '';
  const section = localStorage.getItem('section') || '';
  const deptLabel = [department, section].filter(Boolean).join('/') || '未知部门';

  const roleLabel = Array.from(new Set(loadRoles().map((r) => ROLE_LABELS[r.role]))).join('、') || ROLE_LABELS.MEMBER;

  const handleLogout = () => {
    localStorage.clear();
    navigate('/login');
  };

  const visibleMenu = MENU_ITEMS.filter((m) => m.visible()).map(({ key, icon, label }) => ({ key, icon, label }));

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={220} theme="light" style={{ borderRight: '1px solid #f0f0f0' }}>
        <div style={{ padding: '20px 16px 12px', textAlign: 'center' }}>
          <Typography.Title level={4} style={{ margin: 0 }}>AI 数据平台</Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>文档脱敏与索引管理</Typography.Text>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={visibleMenu}
          onClick={({ key }) => navigate(key)}
          style={{ borderRight: 'none' }}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px', display: 'flex', justifyContent: 'flex-end', alignItems: 'center', borderBottom: '1px solid #f0f0f0' }}>
          <Typography.Text style={{ marginRight: 16 }}>
            {displayName}（{deptLabel} · {roleLabel}）
          </Typography.Text>
          <Button size="small" icon={<LogoutOutlined />} onClick={handleLogout}>退出</Button>
        </Header>
        <Content style={{ margin: 24 }}>
          <Routes>
            <Route path="/documents" element={<DocumentListPage />} />
            <Route
              path="/rules"
              element={
                <RequireRole allow={canManageRules}>
                  <RuleManagePage />
                </RequireRole>
              }
            />
            <Route
              path="/batch"
              element={
                <RequireRole allow={canUseBatch}>
                  <BatchMonitorPage />
                </RequireRole>
              }
            />
            <Route path="/knowledge-graph" element={<KnowledgeGraphPage />} />
            <Route
              path="/users"
              element={
                <RequireRole allow={canManageUsers}>
                  <UserManagePage />
                </RequireRole>
              }
            />
            <Route
              path="/settings"
              element={
                <RequireRole allow={canManageSettings}>
                  <SettingsPage />
                </RequireRole>
              }
            />
            <Route path="*" element={<Navigate to="/documents" replace />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('token');
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function RequireRole({ allow, children }: { allow: () => boolean; children: React.ReactNode }) {
  if (!allow()) {
    return (
      <div style={{ padding: 48, textAlign: 'center' }}>
        <Typography.Title level={4}>权限不足</Typography.Title>
        <Typography.Text type="secondary">您当前的角色无权访问此页面。</Typography.Text>
      </div>
    );
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <ConfigProvider locale={zhCN} theme={{ algorithm: theme.defaultAlgorithm }}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/*"
            element={
              <RequireAuth>
                <AppLayout />
              </RequireAuth>
            }
          />
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}

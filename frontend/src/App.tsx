import React from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { ConfigProvider, Layout, Menu, Typography, Button, theme } from 'antd';
import {
  ApartmentOutlined,
  FileTextOutlined,
  LogoutOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import zhCN from 'antd/locale/zh_CN';

import LoginPage from './pages/LoginPage';
import DocumentListPage from './pages/DocumentListPage';
import RuleManagePage from './pages/RuleManagePage';
import BatchMonitorPage from './pages/BatchMonitorPage';
import SettingsPage from './pages/SettingsPage';
import KnowledgeGraphPage from './pages/KnowledgeGraphPage';

const { Sider, Content, Header } = Layout;

const MENU_ITEMS = [
  { key: '/documents', icon: <FileTextOutlined />, label: '文档管理' },
  { key: '/rules', icon: <SafetyCertificateOutlined />, label: '规则管理' },
  { key: '/batch', icon: <ThunderboltOutlined />, label: 'Batch 监控' },
  { key: '/knowledge-graph', icon: <ApartmentOutlined />, label: '知识图谱' },
  { key: '/settings', icon: <SettingOutlined />, label: '系统设置' },
];

function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const displayName = localStorage.getItem('display_name') || localStorage.getItem('username') || '';
  const department = localStorage.getItem('department') || '';
  const section = localStorage.getItem('section') || '';
  const deptLabel = [department, section].filter(Boolean).join('/') || '未知部门';

  const handleLogout = () => {
    localStorage.clear();
    navigate('/login');
  };

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
          items={MENU_ITEMS}
          onClick={({ key }) => navigate(key)}
          style={{ borderRight: 'none' }}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px', display: 'flex', justifyContent: 'flex-end', alignItems: 'center', borderBottom: '1px solid #f0f0f0' }}>
          <Typography.Text style={{ marginRight: 16 }}>
            {displayName}（{deptLabel}）
          </Typography.Text>
          <Button size="small" icon={<LogoutOutlined />} onClick={handleLogout}>退出</Button>
        </Header>
        <Content style={{ margin: 24 }}>
          <Routes>
            <Route path="/documents" element={<DocumentListPage />} />
            <Route path="/rules" element={<RuleManagePage />} />
            <Route path="/batch" element={<BatchMonitorPage />} />
            <Route path="/knowledge-graph" element={<KnowledgeGraphPage />} />
            <Route path="/settings" element={<SettingsPage />} />
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

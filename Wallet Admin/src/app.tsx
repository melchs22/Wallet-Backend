import type { Settings as LayoutSettings } from '@ant-design/pro-components';
import type { RequestConfig, RunTimeLayoutConfig } from '@umijs/max';
import { history, Link, useLocation } from '@umijs/max';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import React from 'react';

// Initialize dayjs plugins globally
dayjs.extend(relativeTime);

import { AvatarDropdown, ErrorBoundary, LangDropdown, OfflineBanner } from '@/components';
import { currentAdminUser as queryCurrentUser } from '@/services/adminAuth';
import defaultSettings from '../config/defaultSettings';
import { errorConfig } from './requestErrorConfig';

const loginPath = '/user/login';

const adminMenuSections = [
  { title: 'Dashboard', items: [{ path: '/admin/overview', label: 'Overview' }, { path: '/admin/analytics', label: 'Analytics' }] },
  { title: 'User Management', items: [{ path: '/admin/users', label: 'Users' }, { path: '/admin/communications', label: 'Messages' }] },
  { title: 'Financial Operations', items: [{ path: '/admin/transactions', label: 'Transactions' }, { path: '/admin/reports', label: 'Financial Reports' }, { path: '/admin/requests', label: 'Payment Requests' }, { path: '/admin/splits', label: 'Bill Splits' }, { path: '/admin/settlements', label: 'Settlements' }] },
  { title: 'Risk & Compliance', items: [{ path: '/admin/fraud', label: 'Fraud Detection' }, { path: '/admin/disputes', label: 'Disputes' }, { path: '/admin/audit-log', label: 'Audit Trail' }, { path: '/admin/reconciliation', label: 'Reconciliation' }] },
  { title: 'Monitoring & Alerts', items: [{ path: '/admin/monitoring', label: 'System Monitoring' }, { path: '/admin/alerts', label: 'Alert Rules' }] },
  { title: 'Platform Management', items: [{ path: '/admin/merchants', label: 'Merchants' }, { path: '/admin/system', label: 'System Operations' }, { path: '/admin/settings', label: 'Settings' }, { path: '/admin/change-password', label: 'Change Password' }] },
  { title: 'Security & Devices', items: [{ path: '/admin/push-devices', label: 'Push Devices' }, { path: '/admin/trusted-devices', label: 'Trusted Devices' }, { path: '/admin/parental-controls', label: 'Parental Controls' }] },
] as const;

function AdminMenu() {
  const { pathname } = useLocation();
  const [section, setSection] = React.useState<string | null>(() => adminMenuSections.find((group) => group.items.some((item) => pathname.startsWith(item.path)))?.title ?? null);
  const activeGroup = adminMenuSections.find((group) => group.title === section);
  const navigate = (path: string) => history.push(path);

  return (
    <div style={{ height: '100%', overflow: 'hidden', background: '#0f172a', color: '#e2e8f0' }}>
      <div style={{ display: 'flex', height: 72, alignItems: 'center', gap: 12, borderBottom: '1px solid #1e293b', padding: '0 20px' }}>
        <img src="/logo.svg" alt="DSD Admin" style={{ width: 36, height: 36 }} />
        <div><strong style={{ display: 'block', color: '#fff' }}>DSD Admin</strong><small style={{ color: '#94a3b8', letterSpacing: '0.12em' }}>OPERATIONS</small></div>
      </div>
      <div style={{ position: 'relative', height: 'calc(100% - 72px)' }}>
        <div style={{ position: 'absolute', inset: 0, overflowY: 'auto', padding: 16, transform: section ? 'translateX(-100%)' : 'translateX(0)', transition: 'transform 260ms ease' }}>
          <small style={{ display: 'block', margin: '4px 12px 12px', color: '#64748b', fontWeight: 700, letterSpacing: '0.16em' }}>ADMINISTRATION</small>
          {adminMenuSections.map((group) => {
            const active = group.items.some((item) => pathname.startsWith(item.path));
            return <button key={group.title} type="button" onClick={() => setSection(group.title)} style={{ display: 'flex', width: '100%', alignItems: 'center', gap: 12, marginBottom: 8, border: `1px solid ${active ? '#475569' : '#1e293b'}`, borderRadius: 12, background: active ? '#1e293b' : '#111c31', color: '#e2e8f0', padding: '12px', textAlign: 'left', cursor: 'pointer' }}><span style={{ flex: 1 }}><strong style={{ display: 'block', fontSize: 13 }}>{group.title}</strong><small style={{ color: '#64748b' }}>{group.items.length} pages</small></span><span style={{ color: '#94a3b8', fontSize: 20 }}>›</span></button>;
          })}
        </div>
        <div style={{ position: 'absolute', inset: 0, overflowY: 'auto', padding: 16, transform: section ? 'translateX(0)' : 'translateX(100%)', transition: 'transform 260ms ease' }}>
          <button type="button" onClick={() => setSection(null)} style={{ margin: '4px 0 18px', border: 0, background: 'transparent', color: '#94a3b8', cursor: 'pointer' }}>‹&nbsp; All sections</button>
          <small style={{ display: 'block', margin: '0 12px 12px', color: '#64748b', fontWeight: 700, letterSpacing: '0.16em' }}>{section}</small>
          {activeGroup?.items.map((item) => { const active = pathname.startsWith(item.path); return <button key={item.path} type="button" onClick={() => navigate(item.path)} style={{ display: 'block', width: '100%', marginBottom: 4, border: 0, borderRadius: 10, background: active ? '#1e293b' : 'transparent', color: active ? '#fff' : '#cbd5e1', padding: '11px 12px', textAlign: 'left', cursor: 'pointer', fontSize: 13 }}>{item.label}</button>; })}
        </div>
      </div>
    </div>
  );
}

/**
 * @see https://umijs.org/docs/api/runtime-config#getinitialstate
 * */
export async function getInitialState(): Promise<{
  settings?: Partial<LayoutSettings>;
  currentUser?: API.CurrentUser;
  loading?: boolean;
  fetchUserInfo?: () => Promise<API.CurrentUser | undefined>;
  settingDrawerOpen?: boolean;
}> {
  const fetchUserInfo = async () => {
    try {
      return await queryCurrentUser();
    } catch (_error) {
      const { pathname, search, hash } = history.location;
      history.replace(
        `${loginPath}?redirect=${encodeURIComponent(pathname + search + hash)}`,
      );
    }
    return undefined;
  };
  // 如果不是登录页面，执行
  const { location } = history;
  if (
    ![loginPath, '/user/register', '/user/register-result'].includes(
      location.pathname,
    )
  ) {
    const currentUser = await fetchUserInfo();
    return {
      fetchUserInfo,
      currentUser,
      settings: defaultSettings as Partial<LayoutSettings>,
      settingDrawerOpen: false,
    };
  }
  return {
    fetchUserInfo,
    settings: defaultSettings as Partial<LayoutSettings>,
    settingDrawerOpen: false,
  };
}

// ProLayout 支持的api https://procomponents.ant.design/components/layout
export const layout: RunTimeLayoutConfig = ({
  initialState,
  setInitialState,
}) => {
  return {
    menuItemRender: (item, dom) => {
      if (item.path) {
        return (
          <Link to={item.path} prefetch>
            {dom}
          </Link>
        );
      }
      return dom;
    },
    actionsRender: () => {
      return [<LangDropdown key="lang" />];
    },
    avatarProps: {
      src: initialState?.currentUser?.avatar,
      title: 'DSD Admin',
      render: (_, avatarChildren) => (
        <AvatarDropdown>{avatarChildren}</AvatarDropdown>
      ),
    },
    // waterMarkProps: {
    //   content: initialState?.currentUser?.name,
    // },
    footerRender: () => null,
    onPageChange: () => {
      const { location } = history;
      // 如果没有登录，重定向到 login
      if (!initialState?.currentUser && location.pathname !== loginPath) {
        history.replace(
          `${loginPath}?redirect=${encodeURIComponent(location.pathname + location.search + location.hash)}`,
        );
      }
    },
    links: [],
    // Replace ProLayout's default ErrorBoundary with our offline-aware version,
    // so chunk load errors show friendly messages instead of "Something went wrong."
    ErrorBoundary,
    menuHeaderRender: undefined,
    // 自定义 403 页面
    // unAccessible: <div>unAccessible</div>,
    // 增加一个 loading 的状态
    childrenRender: (children) => {
      // if (initialState?.loading) return <PageLoading />;
      return (
        <>{children}</>
      );
    },
    ...initialState?.settings,
  };
};

/**
 * @name request 配置，可以配置错误处理
 * 它基于 axios 提供了一套统一的网络请求和错误处理方案。
 * @doc https://umijs.org/docs/max/request#配置
 */
export const request: RequestConfig = {
  baseURL: process.env.API_BASE_URL || 'http://178.128.156.225/api',
  ...errorConfig,
};

export function rootContainer(container: React.ReactNode) {
  return (
    <>
      <OfflineBanner />
      <ErrorBoundary>{container}</ErrorBoundary>
    </>
  );
}

import { request } from '@umijs/max';

type DjangoUser = {
  id?: number;
  username?: string;
  email?: string;
  display_name?: string;
  avatar_url?: string;
  is_staff?: boolean;
};

const deviceId = () => {
  const existing = localStorage.getItem('wallet_device_id');
  if (existing) return existing;
  const generated = `web-admin-${crypto.randomUUID()}`;
  localStorage.setItem('wallet_device_id', generated);
  return generated;
};

export async function adminLogin(data: { username?: string; password?: string }) {
  const response = await request<{ user: DjangoUser; access_token: string }>('/auth/admin', {
    method: 'POST',
    data,
    credentials: 'include',
  });
  localStorage.setItem('admin_access_token', response.access_token);
  await request('/csrf', { method: 'GET', credentials: 'include' });
  return { status: 'ok', user: response.user };
}

export async function currentAdminUser() {
  const token = localStorage.getItem('admin_access_token');
  const response = await request<{ user: DjangoUser }>('/me', {
    method: 'GET',
    headers: token
      ? { Authorization: `Bearer ${token}`, 'X-Device-ID': deviceId() }
      : {},
    credentials: 'include',
  });
  const user = response.user;
  return {
    name: user.display_name || user.username || user.email,
    userid: String(user.id || ''),
    email: user.email,
    avatar: user.avatar_url,
    access: user.is_staff ? 'admin' : 'user',
  } as API.CurrentUser;
}

export async function adminLogout() {
  try {
    await request('/auth/logout', {
      method: 'POST',
      credentials: 'include',
    });
  } finally {
    localStorage.removeItem('admin_access_token');
    localStorage.removeItem('wallet_device_id');
  }
}
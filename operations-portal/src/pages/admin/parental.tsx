import { ReloadOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { App, Button, Card, Select, Space, Switch, Table, Tag } from 'antd';
import React, { useState } from 'react';
import { getParentalControls, updateParentalControl } from '@/services/admin';
import dayjs from 'dayjs';

const ParentalPage: React.FC = () => {
  const { message } = App.useApp(); const client = useQueryClient(); const [status, setStatus] = useState(''); const query = useQuery({ queryKey: ['parental-controls', status], queryFn: () => getParentalControls({ status }) });
  const update = async (id: number, data: Record<string, unknown>) => { try { await updateParentalControl(id, data); message.success('Parental control updated'); client.invalidateQueries({ queryKey: ['parental-controls'] }); } catch { message.error('Update failed'); } };
  return <PageContainer className="admin-page" title="Parental controls" subTitle="Review child-account relationships and account permissions."><Card className="resource-toolbar"><Space><Select allowClear value={status || undefined} onChange={(value) => setStatus(value || '')} placeholder="Status" options={['pending', 'active', 'revoked'].map((value) => ({ value, label: value }))} /><Button icon={<ReloadOutlined />} onClick={() => query.refetch()}>Refresh</Button></Space></Card><Card><Table rowKey="id" loading={query.isLoading} dataSource={query.data?.controls || []} columns={[{ title: 'Parent', dataIndex: 'parent_handle' }, { title: 'Child', dataIndex: 'child_handle' }, { title: 'Status', dataIndex: 'status', render: (value) => <Tag>{value}</Tag> }, { title: 'View transactions', dataIndex: 'can_view_transactions', render: (value, row) => <Switch checked={value} onChange={(checked) => update(Number(row.id), { can_view_transactions: checked })} /> }, { title: 'Control balance', dataIndex: 'can_control_balance', render: (value, row) => <Switch checked={value} onChange={(checked) => update(Number(row.id), { can_control_balance: checked })} /> }, { title: 'Send money', dataIndex: 'can_send_money', render: (value, row) => <Switch checked={value} onChange={(checked) => update(Number(row.id), { can_send_money: checked })} /> }, { title: 'Linked', dataIndex: 'linked_at', render: (value) => value ? dayjs(value).format('DD MMM YYYY, HH:mm') : '-' }]} pagination={{ pageSize: 15 }} scroll={{ x: 1100 }} /></Card></PageContainer>;
};
export default ParentalPage;
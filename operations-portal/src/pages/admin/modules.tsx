import { CheckOutlined, EyeOutlined, LockOutlined, PlayCircleOutlined, PlusOutlined, ReloadOutlined, SendOutlined, StopOutlined, UnlockOutlined, UserOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { App, Avatar, Button, Card, Col, Descriptions, Drawer, Empty, Form, Image, Input, InputNumber, Modal, Row, Select, Space, Statistic, Table, Tag, Tabs, Typography } from 'antd';
import type { ColumnsType, TableProps } from 'antd/es/table';
import dayjs from 'dayjs';
import React, { useState } from 'react';
import { adminRequest, type AdminRow, getKycSubmissions, getSupportTickets, getTransactions, getUsers, getUserDetail, reviewKyc, freezeWallet, refreshRates, runReconciliation } from '@/services/admin';
import './style.css';

const date = (value: unknown) => value ? dayjs(String(value)).format('DD MMM YYYY, HH:mm') : '-';
const text = (value: unknown) => value && typeof value === 'object' ? ((value as { handle?: string; business_name?: string; email?: string }).handle || (value as { business_name?: string }).business_name || (value as { email?: string }).email || 'Record') : String(value || '-');
const colors: Record<string, string> = { active: 'success', completed: 'success', approved: 'success', open: 'processing', in_progress: 'processing', pending: 'warning', suspended: 'error', frozen: 'error', failed: 'error', rejected: 'error', closed: 'default' };
const labelize = (key: string) => key.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
const walletIsFrozen = (row: AdminRow) => Boolean(row.wallet && typeof row.wallet === 'object' && 'status' in row.wallet && row.wallet.status === 'frozen');
const mediaOrigin = (process.env.API_BASE_URL || '').replace(/\/api\/?$/, '') || window.location.origin;
const mediaUrl = (value: string) => value.startsWith('http') ? value : `${mediaOrigin}${value.startsWith('/') ? value : `/${value}`}`;
const isImage = (value: string) => /\.(png|jpe?g|gif|webp|heic)(\?.*)?$/i.test(value) || /^https?:\/\//i.test(value) || value.startsWith('/media/');

function ReadableValue({ value, fieldName = '' }: { value: unknown; fieldName?: string }) {
  if (value === null || value === undefined || value === '') return <Typography.Text type="secondary">Not provided</Typography.Text>;
  if (typeof value === 'boolean') return <Tag color={value ? 'success' : 'default'}>{value ? 'Yes' : 'No'}</Tag>;
  if (typeof value === 'number' || typeof value === 'string') {
    const stringValue = String(value);
    if ((fieldName.toLowerCase().includes('metadata') || fieldName.toLowerCase().includes('payload') || fieldName.toLowerCase().includes('response')) && /^(?:\{|\[)/.test(stringValue.trim())) {
      try {
        return <ReadableValue value={JSON.parse(stringValue)} fieldName={fieldName} />;
      } catch {
        // Keep malformed provider payloads readable as text.
      }
    }
    if ((fieldName.toLowerCase().includes('document') || fieldName.toLowerCase().includes('image')) && isImage(stringValue)) {
      const url = mediaUrl(stringValue);
      return <Space direction="vertical"><Image width={180} src={url} alt={labelize(fieldName)} /><Button type="link" href={url} target="_blank">Open document</Button></Space>;
    }
    if (fieldName.toLowerCase().includes('at') || fieldName.toLowerCase().includes('date')) return <Typography.Text>{date(value)}</Typography.Text>;
    return <Typography.Text>{stringValue}</Typography.Text>;
  }
  if (Array.isArray(value)) {
    if (!value.length) return <Typography.Text type="secondary">None</Typography.Text>;
    if (value.every((item) => item && typeof item === 'object' && !Array.isArray(item))) {
      const keys = Array.from(new Set(value.flatMap((item) => Object.keys(item as Record<string, unknown>))));
      return <Table size="small" pagination={false} rowKey={(_, index) => String(index)} dataSource={value as Record<string, unknown>[]} columns={keys.map((key) => ({ title: labelize(key), dataIndex: key, render: (item: unknown) => <ReadableValue value={item} fieldName={key} /> }))} />;
    }
    return <Space direction="vertical">{value.map((item) => <Card size="small" key={JSON.stringify(item) ?? String(item)}><ReadableValue value={item} fieldName={fieldName} /></Card>)}</Space>;
  }
  if (typeof value === 'object') return <Descriptions size="small" bordered column={1} items={Object.entries(value as Record<string, unknown>).map(([key, item]) => ({ label: labelize(key), children: <ReadableValue value={item} fieldName={key} /> }))} />;
  return <Typography.Text>{String(value)}</Typography.Text>;
}

function useAction() {
  const { message } = App.useApp();
  const client = useQueryClient();
  return async (work: Promise<unknown>, success: string, key: string) => {
    try {
      await work;
      message.success(success);
      await client.invalidateQueries({ queryKey: [key] });
      return true;
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'The action could not be completed.');
      return false;
    }
  };
}

function RecordsTable({ rows, columns, loading, onView, actions, rowSelection }: { rows: AdminRow[]; columns: ColumnsType<AdminRow>; loading?: boolean; onView?: (row: AdminRow) => void; actions?: (row: AdminRow) => React.ReactNode; rowSelection?: TableProps<AdminRow>['rowSelection'] }) {
  const enhanced = [...columns, { title: 'Actions', key: 'actions', fixed: 'right' as const, render: (_: unknown, row: AdminRow) => <Space>{onView && <Button type="link" icon={<EyeOutlined />} onClick={() => onView(row)}>View</Button>}{actions?.(row)}</Space> }];
  return <Table rowKey={(row) => String(row.id || row.key)} loading={loading} dataSource={rows} columns={enhanced} rowSelection={rowSelection} scroll={{ x: 1000 }} pagination={{ pageSize: 15, showSizeChanger: true }} locale={{ emptyText: <Empty description="No records found" /> }} />;
}

function RecordDrawer({ row, onClose }: { row: AdminRow | null; onClose: () => void }) {
  return <Drawer title="Record details" open={Boolean(row)} onClose={onClose} width={680}>{row ? <Descriptions bordered column={1} items={Object.entries(row).map(([key, value]) => ({ label: labelize(key), children: <ReadableValue value={value} fieldName={key} /> }))} /> : <Empty />}</Drawer>;
}

function UserNotesPanel({ userId }: { userId: number }) {
  const { message } = App.useApp();
  const client = useQueryClient();
  const [form] = Form.useForm<{ note: string }>();
  const notes = useQuery({ queryKey: ['admin-user-notes', userId], queryFn: () => adminRequest<{ notes: AdminRow[] }>(`/admin/users/${userId}/notes`), enabled: userId > 0 });
  const addNote = async ({ note }: { note: string }) => {
    try {
      await adminRequest(`/admin/users/${userId}/notes`, { method: 'POST', data: { note } });
      message.success('Admin note added.');
      form.resetFields();
      await client.invalidateQueries({ queryKey: ['admin-user-notes', userId] });
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'The note could not be saved.');
    }
  };
  if (!userId) return null;
  return <Card title="Internal admin notes" size="small" className="resource-toolbar">
    {notes.isError && <Typography.Text type="danger">Notes could not be loaded.</Typography.Text>}
    <Table size="small" rowKey="id" pagination={{ pageSize: 5 }} loading={notes.isLoading} dataSource={notes.data?.notes || []} columns={[{ title: 'Note', dataIndex: 'note' }, { title: 'Author', dataIndex: 'admin', render: text }, { title: 'Created', dataIndex: 'created_at', render: date }]} />
    <Form form={form} layout="vertical" onFinish={addNote}>
      <Form.Item name="note" rules={[{ required: true, whitespace: true, message: 'Enter a note.' }]}><Input.TextArea maxLength={2000} showCount placeholder="Visible to administrators only" /></Form.Item>
      <Button type="primary" htmlType="submit">Add note</Button>
    </Form>
  </Card>;
}

function TransactionFlagsPanel({ transactionId }: { transactionId: string }) {
  const { message } = App.useApp();
  const client = useQueryClient();
  const [form] = Form.useForm<{ flag_id: number; description: string }>();
  const query = useQuery({ queryKey: ['admin-transaction-flags', transactionId], queryFn: () => adminRequest<{ flags: AdminRow[] }>(`/admin/transactions/${transactionId}/flags`) });
  const addFlag = async (values: { flag_id: number; description?: string }) => {
    try {
      await adminRequest(`/admin/transactions/${transactionId}/flags`, { method: 'POST', data: values });
      message.success('Transaction flag added.');
      form.resetFields();
      await client.invalidateQueries({ queryKey: ['admin-transaction-flags', transactionId] });
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Transaction flag could not be added.');
    }
  };
  const removeFlag = (flagId: unknown) => Modal.confirm({
    title: 'Remove transaction flag?',
    onOk: async () => {
      try {
        await adminRequest(`/admin/transactions/${transactionId}/flags`, { method: 'DELETE', data: { flag_id: flagId } });
        message.success('Transaction flag removed.');
        await client.invalidateQueries({ queryKey: ['admin-transaction-flags', transactionId] });
      } catch (error) {
        message.error(error instanceof Error ? error.message : 'Transaction flag could not be removed.');
        throw error;
      }
    },
  });
  return <Card title="Risk and review flags" size="small" className="resource-toolbar">
    {query.isError && <Typography.Text type="danger">Transaction flags could not be loaded.</Typography.Text>}
    <Table size="small" rowKey="id" pagination={false} loading={query.isLoading} dataSource={query.data?.flags || []} columns={[{ title: 'Flag', dataIndex: 'flag_name' }, { title: 'Description', dataIndex: 'description' }, { title: 'Created', dataIndex: 'created_at', render: date }, { title: 'Action', render: (_, flag) => <Button danger type="link" onClick={() => removeFlag(flag.id)}>Remove</Button> }]} />
    <Form form={form} layout="vertical" onFinish={addFlag} className="resource-toolbar">
      <Form.Item name="flag_id" label="Flag type" rules={[{ required: true }]}><Select options={[['high_risk', 1], ['requires_review', 2], ['suspicious', 3], ['vip', 4], ['priority', 5], ['compliance', 6], ['fraud_investigation', 7]].map(([label, id]) => ({ label, value: id }))} /></Form.Item>
      <Form.Item name="description" label="Reason / context"><Input.TextArea maxLength={1000} /></Form.Item>
      <Button type="primary" htmlType="submit">Add flag</Button>
    </Form>
  </Card>;
}

function TransactionDrawer({ row, onClose }: { row: AdminRow | null; onClose: () => void }) {
  return <Drawer title="Transaction details" open={Boolean(row)} onClose={onClose} width={720}>
    {row && <><Descriptions bordered column={1} items={Object.entries(row).map(([key, value]) => ({ label: labelize(key), children: <ReadableValue value={value} fieldName={key} /> }))} /><TransactionFlagsPanel transactionId={String(row.id)} /></>}
  </Drawer>;
}

export const UsersPage: React.FC = () => {
  const { message } = App.useApp(); const run = useAction(); const [q, setQ] = useState(''); const [status, setStatus] = useState(''); const [row, setRow] = useState<AdminRow | null>(null); const [topup, setTopup] = useState<AdminRow | null>(null); const [freezeTarget, setFreezeTarget] = useState<AdminRow | null>(null); const [bulkOpen, setBulkOpen] = useState(false); const [selectedUsers, setSelectedUsers] = useState<React.Key[]>([]); const [form] = Form.useForm(); const [bulkForm] = Form.useForm<{ action: string; reason: string }>(); const [freezeForm] = Form.useForm<{ reason: string }>();
  const query = useQuery({ queryKey: ['admin-users-page', q, status], queryFn: () => getUsers({ query: q, status, page_size: 100 }) }); const rows = query.data?.results || [];
  const detail = useQuery({ queryKey: ['admin-user-detail', row?.id], queryFn: () => getUserDetail(Number(row?.id)), enabled: Boolean(row?.id) });
  const submitTopup = async (values: { amount: number; currency: string; reason: string }) => { const succeeded = await run(adminRequest(`/admin/users/${topup?.id}/topup`, { method: 'POST', data: values }), 'Top-up created', 'admin-users-page'); if (succeeded) { setTopup(null); form.resetFields(); } };
  const submitBulkAction = async (values: { action: string; reason: string }) => {
    try {
      const result = await adminRequest<{ processed: number; successful: number }>('/admin/users/bulk-action', { method: 'POST', data: { user_ids: selectedUsers.map(Number), ...values } });
      if (result.successful < result.processed) message.warning(`${result.successful} of ${result.processed} selected accounts updated; review audit logs for failed records.`);
      else message.success(`${result.successful} accounts updated.`);
      setSelectedUsers([]);
      setBulkOpen(false);
      bulkForm.resetFields();
      await query.refetch();
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Bulk action failed.');
    }
  };
  const submitFreeze = async ({ reason }: { reason: string }) => {
    if (!freezeTarget) return;
    const succeeded = await run(freezeWallet(Number(freezeTarget.id), reason), 'Wallet status changed', 'admin-users-page');
    if (succeeded) {
      setFreezeTarget(null);
      freezeForm.resetFields();
    }
  };
  return <PageContainer className="admin-page" title="Users" subTitle="Manage customer identity, access, wallet controls, and manual funding."><Card className="resource-toolbar"><Space wrap><Input.Search allowClear value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search handle, email, phone" style={{ width: 300 }} /><Select allowClear value={status || undefined} onChange={(value) => setStatus(value || '')} placeholder="Account status" options={['active', 'suspended', 'closed'].map((value) => ({ value, label: value }))} /><Button icon={<ReloadOutlined />} onClick={() => query.refetch()}>Refresh</Button><Button disabled={!selectedUsers.length} onClick={() => setBulkOpen(true)}>Bulk action ({selectedUsers.length})</Button></Space></Card><Card><RecordsTable rows={rows as AdminRow[]} loading={query.isLoading} rowSelection={{ selectedRowKeys: selectedUsers, onChange: setSelectedUsers }} onView={setRow} columns={[{ title: 'Handle', dataIndex: 'handle' }, { title: 'Email', dataIndex: 'email' }, { title: 'Status', dataIndex: 'status', render: (value) => <Tag color={colors[value] || 'default'}>{value}</Tag> }, { title: 'KYC', dataIndex: 'kyc_tier' }, { title: 'Created', dataIndex: 'created_at', render: date }]} actions={(record) => <><Button type="link" icon={walletIsFrozen(record) ? <UnlockOutlined /> : <LockOutlined />} onClick={() => { setFreezeTarget(record); freezeForm.resetFields(); }}>{walletIsFrozen(record) ? 'Unfreeze' : 'Freeze'}</Button><Button type="link" icon={<PlusOutlined />} onClick={() => setTopup(record)}>Top up</Button></>} /></Card><Drawer title={detail.data?.display_name || detail.data?.handle || 'User profile'} open={Boolean(row)} onClose={() => setRow(null)} width={760}>{detail.isLoading ? <Typography.Text>Loading profile...</Typography.Text> : detail.data && <><div className="profile-summary"><Avatar size={64} src={detail.data.avatar_url} icon={<UserOutlined />} /><div><Typography.Title level={3}>{detail.data.display_name || detail.data.handle}</Typography.Title><Typography.Text type="secondary">{detail.data.email} · @{detail.data.handle}</Typography.Text></div><Tag color={colors[detail.data.status || '']}>{detail.data.status}</Tag></div><Descriptions bordered column={2} items={[['KYC tier', detail.data.kyc_tier], ['Wallet status', detail.data.wallet_status], ['Balance', `${detail.data.balance || '0.00'} GNF`], ['Joined', date(detail.data.created_at)], ['Per transaction limit', detail.data.send_limit_per_tx], ['Daily limit', detail.data.send_limit_daily]].map(([label, children]) => ({ label, children: children || 'Not set' }))} /><Typography.Title level={5}>Recent transactions</Typography.Title><Table size="small" rowKey="id" pagination={false} dataSource={(detail.data.recent_transactions || []) as AdminRow[]} columns={[{ title: 'Reference', dataIndex: 'id' }, { title: 'Type', dataIndex: 'type' }, { title: 'Sender', dataIndex: 'sender_handle' }, { title: 'Receiver', dataIndex: 'recipient_handle' }, { title: 'Amount', render: (_, record) => `${record.amount || '-'} ${record.currency || ''}` }, { title: 'Status', dataIndex: 'status', render: (value) => <Tag color={colors[value] || 'default'}>{value}</Tag> }]} scroll={{ x: 650 }} /></>}<UserNotesPanel userId={Number(row?.id)} /></Drawer><Modal title="Bulk user operation" open={bulkOpen} onCancel={() => setBulkOpen(false)} onOk={() => bulkForm.submit()} okText="Apply to selected users"><Form form={bulkForm} layout="vertical" onFinish={submitBulkAction}><Form.Item name="action" label="Operation" rules={[{ required: true }]}><Select options={[{ value: 'suspend', label: 'Suspend accounts' }, { value: 'activate', label: 'Activate accounts' }, { value: 'freeze', label: 'Freeze wallets' }, { value: 'unfreeze', label: 'Unfreeze wallets' }]} /></Form.Item><Form.Item name="reason" label="Audit reason" rules={[{ required: true, whitespace: true }]}><Input.TextArea maxLength={500} showCount /></Form.Item></Form></Modal><Modal title={`${walletIsFrozen(freezeTarget || {}) ? 'Unfreeze' : 'Freeze'} wallet for ${text(freezeTarget?.handle)}?`} open={Boolean(freezeTarget)} onCancel={() => setFreezeTarget(null)} onOk={() => freezeForm.submit()}><Form form={freezeForm} layout="vertical" onFinish={submitFreeze}><Form.Item name="reason" label="Audit reason" rules={[{ required: true, whitespace: true, message: 'A reason is required.' }]}><Input.TextArea maxLength={500} showCount /></Form.Item></Form></Modal><Modal title={`Top up ${text(topup?.handle)}`} open={Boolean(topup)} onCancel={() => setTopup(null)} onOk={() => form.submit()}><Form form={form} layout="vertical" onFinish={submitTopup}><Form.Item name="amount" label="Amount" rules={[{ required: true }]}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item><Form.Item name="currency" label="Currency" initialValue="GNF"><Input /></Form.Item><Form.Item name="reason" label="Reason" rules={[{ required: true }]}><Input.TextArea /></Form.Item></Form></Modal></PageContainer>;
};

export const TransactionsPage: React.FC = () => {
  const run = useAction();
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [row, setRow] = useState<AdminRow | null>(null);
  const [reversing, setReversing] = useState<AdminRow | null>(null);
  const [reasonForm] = Form.useForm<{ reason: string }>();
  const query = useQuery({ queryKey: ['admin-transactions-page', q, status], queryFn: () => getTransactions({ query: q, status, page_size: 100 }) });
  const rows = query.data?.results || [];
  const submitReversal = async ({ reason }: { reason: string }) => {
    if (!reversing) return;
    const success = await run(adminRequest(`/admin/transactions/${reversing.id}/reverse`, { method: 'POST', data: { reason } }), 'Transaction reversal created', 'admin-transactions-page');
    if (success) {
      setReversing(null);
      reasonForm.resetFields();
    }
  };
  return <PageContainer className="admin-page" title="Transactions" subTitle="Inspect ledger movement, statuses, flags, and auditable reversals.">
    <Card className="resource-toolbar"><Space wrap><Input.Search allowClear value={q} onChange={(e) => setQ(e.target.value)} placeholder="Reference or handle" style={{ width: 300 }} /><Select allowClear value={status || undefined} onChange={(value) => setStatus(value || '')} placeholder="Transaction status" options={['pending', 'completed', 'failed', 'reversed'].map((value) => ({ value, label: value }))} /><Button icon={<ReloadOutlined />} onClick={() => query.refetch()}>Refresh</Button></Space></Card>
    <Card><RecordsTable rows={rows as AdminRow[]} loading={query.isLoading} onView={setRow} columns={[{ title: 'Reference', dataIndex: 'id' }, { title: 'Type', dataIndex: 'type' }, { title: 'Sender', dataIndex: 'sender', render: text }, { title: 'Recipient', dataIndex: 'recipient', render: text }, { title: 'Amount', render: (_, record) => `${record.amount || '-'} ${record.currency || ''}` }, { title: 'Status', dataIndex: 'status', render: (value) => <Tag color={colors[value]}>{value}</Tag> }, { title: 'Created', dataIndex: 'created_at', render: date }]} actions={(record) => record.status === 'completed' && <Button danger type="link" icon={<StopOutlined />} onClick={() => { setReversing(record); reasonForm.resetFields(); }}>Reverse</Button>} /></Card>
    <TransactionDrawer row={row} onClose={() => setRow(null)} />
    <Modal title={`Reverse transaction ${String(reversing?.id || '')}`} open={Boolean(reversing)} onCancel={() => setReversing(null)} onOk={() => reasonForm.submit()} okButtonProps={{ danger: true }} okText="Create reversal">
      <Typography.Paragraph>This creates an offsetting ledger transaction. Provide the reason that will be recorded for audit.</Typography.Paragraph>
      <Form form={reasonForm} layout="vertical" onFinish={submitReversal}><Form.Item name="reason" label="Reversal reason" rules={[{ required: true, whitespace: true, message: 'A reversal reason is required.' }]}><Input.TextArea maxLength={1000} showCount /></Form.Item></Form>
    </Modal>
  </PageContainer>;
};

export const SupportPage: React.FC = () => {
  const run = useAction();
  const [status, setStatus] = useState('');
  const [row, setRow] = useState<AdminRow | null>(null);
  const [reply, setReply] = useState('');
  const [internalNote, setInternalNote] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm();
  const query = useQuery({ queryKey: ['admin-support-page', status], queryFn: () => getSupportTickets({ status }) });
  const metrics = useQuery({ queryKey: ['admin-support-page-metrics'], queryFn: () => adminRequest<{ total_tickets: number; open_tickets: number; in_progress: number; unassigned: number }>('/admin/support/metrics') });
  const detail = useQuery({ queryKey: ['admin-support-detail', row?.id], queryFn: () => adminRequest<AdminRow>(`/admin/support/tickets/${row?.id}`), enabled: Boolean(row?.id) });
  const team = useQuery({ queryKey: ['admin-support-team'], queryFn: () => adminRequest<{ team_members: AdminRow[] }>('/admin/team') });
  const rows = query.data?.tickets || [];
  const ticket = detail.data || row;
  const update = async (data: AdminRow) => {
    if (!row) return;
    const success = await run(adminRequest(`/admin/support/tickets/${row.id}/update`, { method: 'PATCH', data }), 'Ticket updated', 'admin-support-page');
    if (success) await detail.refetch();
  };
  const sendReply = async () => {
    if (!row || !reply.trim()) return;
    const success = await run(adminRequest(`/admin/support/tickets/${row.id}/messages`, { method: 'POST', data: { message: reply, is_internal_note: internalNote } }), internalNote ? 'Internal note added' : 'Reply sent', 'admin-support-page');
    if (success) {
      setReply('');
      await detail.refetch();
    }
  };
  const createTicket = async (values: AdminRow) => {
    const success = await run(adminRequest('/admin/support/tickets', { method: 'POST', data: values }), 'Support ticket created', 'admin-support-page');
    if (success) {
      setCreateOpen(false);
      createForm.resetFields();
    }
  };
  return <PageContainer className="admin-page" title="Support tickets" subTitle="Review ticket details, assign staff, manage priority and status, and maintain customer or internal threads.">
    {metrics.isError && <Typography.Text type="danger">Support metrics could not be loaded.</Typography.Text>}
    <Row gutter={[16, 16]} className="metric-row">{[['All tickets', metrics.data?.total_tickets], ['Open', metrics.data?.open_tickets], ['In progress', metrics.data?.in_progress], ['Unassigned', metrics.data?.unassigned]].map(([title, number]) => <Col xs={12} lg={6} key={String(title)}><Card className="metric-card" loading={metrics.isLoading}><Statistic title={String(title)} value={typeof number === 'number' ? number : '—'} /></Card></Col>)}</Row>
    <Card className="resource-toolbar"><Space><Select allowClear value={status || undefined} onChange={(value) => setStatus(value || '')} placeholder="Ticket status" options={['open', 'in_progress', 'waiting_on_user', 'resolved', 'closed'].map((value) => ({ value, label: value }))} /><Button icon={<ReloadOutlined />} onClick={() => query.refetch()}>Refresh</Button><Button type="primary" onClick={() => setCreateOpen(true)}>Create ticket</Button></Space></Card>
    <Card><RecordsTable rows={rows as AdminRow[]} loading={query.isLoading} onView={setRow} columns={[{ title: 'Ticket', dataIndex: 'ticket_number' }, { title: 'Subject', dataIndex: 'subject' }, { title: 'Customer', dataIndex: 'user', render: text }, { title: 'Priority', dataIndex: 'priority', render: (value) => <Tag color={value === 'urgent' ? 'red' : 'blue'}>{value}</Tag> }, { title: 'Status', dataIndex: 'status', render: (value) => <Tag color={colors[value]}>{value}</Tag> }, { title: 'Updated', dataIndex: 'updated_at', render: date }]} actions={(record) => <Button type="link" onClick={() => setRow(record)}>Open</Button>} /></Card>
    {query.isError && <Typography.Text type="danger">Ticket list could not be loaded.</Typography.Text>}
    <Drawer title={ticket ? `${text(ticket.ticket_number)} · ${text(ticket.subject)}` : 'Ticket'} open={Boolean(row)} onClose={() => setRow(null)} width={720}>
      {detail.isLoading && <Typography.Text>Loading ticket details…</Typography.Text>}
      {detail.isError && <Typography.Text type="danger">Ticket details could not be loaded.</Typography.Text>}
      {ticket && <>
        <Descriptions bordered column={1} items={[{ label: 'Customer', children: text(ticket.user) }, { label: 'Related transaction', children: text(ticket.related_transaction) }, { label: 'Created', children: date(ticket.created_at) }]} />
        <Space wrap className="resource-toolbar">
          <Select value={String(ticket.status || '')} onChange={(value) => update({ status: value })} options={['open', 'in_progress', 'waiting_on_user', 'resolved', 'closed'].map((value) => ({ value, label: `Status: ${value}` }))} />
          <Select value={String(ticket.priority || '')} onChange={(value) => update({ priority: value })} options={['low', 'medium', 'high', 'urgent'].map((value) => ({ value, label: `Priority: ${value}` }))} />
          <Select allowClear placeholder="Assign staff member" value={typeof ticket.assigned_to === 'object' && ticket.assigned_to !== null ? String((ticket.assigned_to as AdminRow).id) : undefined} onChange={(value) => update({ assigned_to_id: value ? Number(value) : null })} loading={team.isLoading} options={(team.data?.team_members || []).map((member) => ({ value: String(member.id), label: String(member.username || member.email || member.id) }))} />
        </Space>
        <Typography.Title level={5}>Conversation and internal notes</Typography.Title>
        {Array.isArray(ticket.messages) && ticket.messages.length ? ticket.messages.map((item, index) => <Card size="small" key={String(item.id || index)} className="thread-message" title={<Space><Typography.Text strong>{text(item.sender)}</Typography.Text>{item.is_internal_note && <Tag color="orange">Internal</Tag>}</Space>}><Typography.Paragraph>{text(item.message)}</Typography.Paragraph><Typography.Text type="secondary">{date(item.created_at)}</Typography.Text></Card>) : <Empty description="No messages" />}
        <Input.TextArea value={reply} onChange={(event) => setReply(event.target.value)} maxLength={5000} showCount placeholder={internalNote ? 'Write an internal staff note' : 'Write a customer reply'} className="resource-toolbar" />
        <Space><Button onClick={() => setInternalNote(!internalNote)}>{internalNote ? 'Switch to customer reply' : 'Add internal note'}</Button><Button type="primary" icon={<SendOutlined />} disabled={!reply.trim()} onClick={sendReply}>{internalNote ? 'Save note' : 'Send reply'}</Button></Space>
      </>}
    </Drawer>
    <Modal title="Create support ticket" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={() => createForm.submit()}>
      <Form form={createForm} layout="vertical" onFinish={createTicket}>
        <Form.Item name="user_id" label="Customer user ID" rules={[{ required: true }]}><InputNumber min={1} precision={0} style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="subject" label="Subject" rules={[{ required: true, whitespace: true }]}><Input maxLength={255} /></Form.Item>
        <Form.Item name="category" label="Category" initialValue="general" rules={[{ required: true }]}><Select options={['general', 'billing', 'transfer', 'account', 'kyc', 'fraud'].map((item) => ({ value: item, label: item }))} /></Form.Item>
        <Form.Item name="priority" label="Priority" initialValue="medium" rules={[{ required: true }]}><Select options={['low', 'medium', 'high', 'urgent'].map((item) => ({ value: item, label: item }))} /></Form.Item>
        <Form.Item name="related_transaction_id" label="Related transaction ID"><Input /></Form.Item>
        <Form.Item name="initial_message" label="Initial message" rules={[{ required: true, whitespace: true }]}><Input.TextArea maxLength={5000} showCount /></Form.Item>
      </Form>
    </Modal>
  </PageContainer>;
};

export const KycPage: React.FC = () => {
  const run = useAction();
  const [status, setStatus] = useState('pending');
  const [row, setRow] = useState<AdminRow | null>(null);
  const [reviewing, setReviewing] = useState<'approve' | 'reject' | null>(null);
  const [reviewForm] = Form.useForm<{ target_kyc_tier: string; reviewer_notes: string }>();
  const query = useQuery({ queryKey: ['admin-kyc-page', status], queryFn: () => getKycSubmissions(status) });
  const rows = query.data?.submissions || [];
  const submitReview = async (values: { target_kyc_tier: string; reviewer_notes: string }) => {
    if (!row || !reviewing) return;
    const success = await run(reviewKyc(Number(row.id), { ...values, action: reviewing }), `KYC ${reviewing === 'approve' ? 'approved' : 'rejected'}`, 'admin-kyc-page');
    if (success) {
      setReviewing(null);
      setRow(null);
      reviewForm.resetFields();
    }
  };
  const openReview = (record: AdminRow, action: 'approve' | 'reject') => {
    setRow(record);
    setReviewing(action);
    reviewForm.setFieldsValue({ target_kyc_tier: 'tier_1', reviewer_notes: '' });
  };
  return <PageContainer className="admin-page" title="KYC review" subTitle="Review identity documents and record a verification tier and reviewer decision.">
    <Card className="resource-toolbar"><Space><Select value={status} onChange={setStatus} options={['pending', 'approved', 'rejected'].map((value) => ({ value, label: value }))} /><Button icon={<ReloadOutlined />} onClick={() => query.refetch()}>Refresh</Button></Space></Card>
    <Card><RecordsTable rows={rows} loading={query.isLoading} onView={setRow} columns={[{ title: 'Applicant', dataIndex: 'user', render: text }, { title: 'Document', dataIndex: 'document_type' }, { title: 'Preview', dataIndex: 'document', render: (value) => <ReadableValue value={value} fieldName="document" /> }, { title: 'Status', dataIndex: 'status', render: (value) => <Tag color={colors[value]}>{value}</Tag> }, { title: 'Submitted', dataIndex: 'created_at', render: date }]} actions={(record) => record.status === 'pending' && <><Button type="link" icon={<CheckOutlined />} onClick={() => openReview(record, 'approve')}>Approve</Button><Button danger type="link" onClick={() => openReview(record, 'reject')}>Reject</Button></>} /></Card>
    <RecordDrawer row={reviewing ? null : row} onClose={() => setRow(null)} />
    <Modal title={`KYC ${reviewing === 'approve' ? 'approval' : 'rejection'}`} open={Boolean(reviewing)} onCancel={() => setReviewing(null)} onOk={() => reviewForm.submit()} okButtonProps={reviewing === 'reject' ? { danger: true } : undefined}>
      <Typography.Paragraph>Record the reviewer rationale for this identity-verification decision.</Typography.Paragraph>
      <Form form={reviewForm} layout="vertical" onFinish={submitReview}>
        {reviewing === 'approve' && <Form.Item name="target_kyc_tier" label="Approved tier" rules={[{ required: true }]}><Select options={[{ value: 'tier_1', label: 'Tier 1' }, { value: 'tier_2', label: 'Tier 2' }]} /></Form.Item>}
        <Form.Item name="reviewer_notes" label="Reviewer notes" rules={[{ required: true, whitespace: true, message: 'A reviewer rationale is required.' }]}><Input.TextArea maxLength={1000} showCount /></Form.Item>
      </Form>
    </Modal>
  </PageContainer>;
};

export const OperationsPage: React.FC = () => {
  const run = useAction(); const initialTab = window.location.pathname.includes('mobile-money') ? 'mobile' : window.location.pathname.includes('webhooks') ? 'webhooks' : 'tasks'; const [tab, setTab] = useState(initialTab); const [q, setQ] = useState(''); const endpoints: Record<string, { path: string; key: string; extract: string }> = { tasks: { path: '/admin/tasks/periodic', key: 'tasks', extract: 'tasks' }, mobile: { path: '/admin/mobile-money/transactions', key: 'mobile', extract: 'transactions' }, webhooks: { path: '/admin/merchants/webhooks/failed', key: 'webhooks', extract: 'failed_webhooks' } }; const endpoint = endpoints[tab]; const query = useQuery({ queryKey: ['admin-operations-page', tab, q], queryFn: () => adminRequest<Record<string, AdminRow[]>>(endpoint.path, { params: { query: q } }) }); const rows = query.data?.[endpoint.extract] || [];
  const action = (_record: AdminRow, path: string, label: string) => run(adminRequest(path, { method: 'POST', data: {} }), label, 'admin-operations-page');
  return <PageContainer className="admin-page" title="Operations" subTitle="Control scheduled jobs, payment rails, and failed integrations."><Tabs activeKey={tab} onChange={setTab} items={[{ key: 'tasks', label: 'Scheduled tasks' }, { key: 'mobile', label: 'Mobile money' }, { key: 'webhooks', label: 'Failed webhooks' }]} /><Card className="resource-toolbar"><Space><Input.Search allowClear value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search operations" /><Button icon={<ReloadOutlined />} onClick={() => query.refetch()}>Refresh</Button></Space></Card><Card><RecordsTable rows={rows} loading={query.isLoading} onView={(record) => Modal.info({ title: tab === 'tasks' ? text(record.name) : 'Operation details', content: <ReadableValue value={record} />, width: 760 })} columns={tab === 'tasks' ? [{ title: 'Name', dataIndex: 'name' }, { title: 'Task', dataIndex: 'task' }, { title: 'Schedule', dataIndex: 'schedule_description' }, { title: 'Enabled', dataIndex: 'enabled', render: (value) => <Tag color={value ? 'success' : 'default'}>{value ? 'Enabled' : 'Disabled'}</Tag> }, { title: 'Last run', dataIndex: 'last_run_at', render: date }] : tab === 'mobile' ? [{ title: 'Reference', dataIndex: 'provider_transaction_id' }, { title: 'User', dataIndex: 'user', render: text }, { title: 'Type', dataIndex: 'type' }, { title: 'Amount', dataIndex: 'amount' }, { title: 'Status', dataIndex: 'status', render: (value) => <Tag color={colors[value]}>{value}</Tag> }] : [{ title: 'Merchant', dataIndex: 'merchant_name' }, { title: 'Event', dataIndex: 'event_type' }, { title: 'Attempts', dataIndex: 'attempt_count' }, { title: 'Error', dataIndex: 'last_error' }, { title: 'Created', dataIndex: 'created_at', render: date }]} actions={(record) => tab === 'tasks' ? <><Button type="link" icon={<PlayCircleOutlined />} onClick={() => action(record, `/admin/tasks/periodic/${record.id}/run-now`, 'Task queued')}>Run now</Button><Button type="link" onClick={() => action(record, `/admin/tasks/periodic/${record.id}/toggle`, 'Task toggled')}>Toggle</Button></> : <Button type="link" icon={<ReloadOutlined />} onClick={() => action(record, tab === 'mobile' ? `/admin/mobile-money/transactions/${record.id}/retry` : `/admin/merchants/webhooks/${record.id}/retry`, 'Retry queued')}>Retry</Button>} /></Card></PageContainer>;
};

export const FinancePage: React.FC = () => {
  const { message } = App.useApp(); const run = useAction(); const [tab, setTab] = useState(window.location.pathname.includes('fee-rules') ? 'fees' : 'rates'); const [form] = Form.useForm(); const query = useQuery({ queryKey: ['admin-finance-page', tab], queryFn: () => adminRequest<Record<string, AdminRow[]>>(tab === 'rates' ? '/admin/finance/exchange-rates' : '/admin/finance/fee-rules') }); const rows = query.data?.[tab === 'rates' ? 'exchange_rates' : 'rules'] || [];
  const createRule = async (values: AdminRow) => { try { await adminRequest('/admin/finance/fee-rules', { method: 'POST', data: values }); message.success('Fee rule created'); form.resetFields(); query.refetch(); } catch (error) { message.error(error instanceof Error ? error.message : 'Fee rule could not be created'); } };
  return <PageContainer className="admin-page" title="Finance controls" subTitle="Manage exchange rates, transfer fee bands, and reconciliation controls." extra={<Space><Button icon={<ReloadOutlined />} onClick={() => query.refetch()}>Refresh</Button><Button type="primary" onClick={() => run(runReconciliation(), 'Reconciliation queued', 'admin-finance-page')}>Run reconciliation</Button></Space>}><Tabs activeKey={tab} onChange={setTab} items={[{ key: 'rates', label: 'Exchange rates' }, { key: 'fees', label: 'Fee rules' }]} /><Card>{tab === 'rates' ? <><Button className="table-action" onClick={() => run(refreshRates(), 'Rate refresh queued', 'admin-finance-page')}>Refresh provider rates</Button><Table rowKey="id" loading={query.isLoading} dataSource={rows} columns={[{ title: 'From', dataIndex: 'from_currency' }, { title: 'To', dataIndex: 'to_currency' }, { title: 'Rate', dataIndex: 'rate' }, { title: 'Source', dataIndex: 'source' }, { title: 'Valid from', dataIndex: 'valid_from', render: date }]} /></> : <><Form form={form} layout="inline" onFinish={createRule} className="inline-form"><Form.Item name="min_amount" rules={[{ required: true }]}><InputNumber placeholder="Min" /></Form.Item><Form.Item name="max_amount"><InputNumber placeholder="Max" /></Form.Item><Form.Item name="fee_type" initialValue="flat"><Select options={[{ value: 'flat' }, { value: 'percentage' }]} /></Form.Item><Form.Item name="fee_value" rules={[{ required: true }]}><InputNumber placeholder="Fee" /></Form.Item><Form.Item name="active" initialValue><Button type="primary" htmlType="submit" icon={<PlusOutlined />}>Add rule</Button></Form.Item></Form><Table rowKey="id" loading={query.isLoading} dataSource={rows} columns={[{ title: 'Minimum', dataIndex: 'min_amount' }, { title: 'Maximum', dataIndex: 'max_amount' }, { title: 'Type', dataIndex: 'fee_type' }, { title: 'Value', dataIndex: 'fee_value' }, { title: 'Active', dataIndex: 'active', render: (value) => <Tag color={value ? 'success' : 'default'}>{String(value)}</Tag> }]} /></>}</Card></PageContainer>;
};

export const MerchantsPage: React.FC = () => {
  const run = useAction(); const [row, setRow] = useState<AdminRow | null>(null); const [rejectTarget, setRejectTarget] = useState<AdminRow | null>(null); const [rejectForm] = Form.useForm<{ rejection_reason: string }>(); const query = useQuery({ queryKey: ['admin-merchants-page'], queryFn: () => adminRequest<AdminRow[]>('/admin/merchants') }); const detail = useQuery({ queryKey: ['admin-merchant-detail', row?.id], queryFn: () => adminRequest<AdminRow>(`/admin/merchants/${row?.id}`), enabled: Boolean(row?.id) }); const rows = Array.isArray(query.data) ? query.data : [];
  const rejectMerchant = async ({ rejection_reason }: { rejection_reason: string }) => {
    if (!rejectTarget) return;
    const success = await run(adminRequest(`/admin/merchants/${rejectTarget.id}/approve`, { method: 'POST', data: { action: 'reject', rejection_reason } }), 'Merchant rejected', 'admin-merchants-page');
    if (success) { setRejectTarget(null); rejectForm.resetFields(); }
  };
  return <PageContainer className="admin-page" title="Merchants" subTitle="Review merchant accounts and inspect profile, settlement, webhook, and recent activity details."><Card className="resource-toolbar"><Button icon={<ReloadOutlined />} onClick={() => query.refetch()}>Refresh</Button></Card><Card><RecordsTable rows={rows} loading={query.isLoading} onView={setRow} columns={[{ title: 'Business', dataIndex: 'business_name' }, { title: 'Owner', dataIndex: 'owner', render: text }, { title: 'Plan', dataIndex: 'plan' }, { title: 'Status', dataIndex: 'status', render: (value) => <Tag color={colors[value]}>{value}</Tag> }, { title: 'Created', dataIndex: 'created_at', render: date }]} actions={(record) => record.status === 'pending' && <><Button type="link" icon={<CheckOutlined />} onClick={() => run(adminRequest(`/admin/merchants/${record.id}/approve`, { method: 'POST', data: { action: 'approve' } }), 'Merchant approved', 'admin-merchants-page')}>Approve</Button><Button danger type="link" onClick={() => { setRejectTarget(record); rejectForm.resetFields(); }}>Reject</Button></>} /></Card><Drawer title={row ? `Merchant ${text(row.business_name)}` : 'Merchant details'} open={Boolean(row)} onClose={() => setRow(null)} width={760}>{detail.isLoading ? <Typography.Text>Loading merchant profile…</Typography.Text> : detail.isError ? <Typography.Text type="danger">Merchant details could not be loaded.</Typography.Text> : detail.data && <Descriptions bordered column={1} items={Object.entries(detail.data).filter(([key]) => key !== 'sandbox_public_key' && key !== 'live_public_key').map(([key, value]) => ({ label: labelize(key), children: <ReadableValue value={value} fieldName={key} /> }))} />}</Drawer><Modal title={`Reject ${text(rejectTarget?.business_name)}?`} open={Boolean(rejectTarget)} onCancel={() => setRejectTarget(null)} onOk={() => rejectForm.submit()} okButtonProps={{ danger: true }}><Form form={rejectForm} layout="vertical" onFinish={rejectMerchant}><Form.Item name="rejection_reason" label="Reason" rules={[{ required: true, whitespace: true }]}><Input.TextArea maxLength={1000} showCount /></Form.Item></Form></Modal></PageContainer>;
};

export const AdminRecordsPage: React.FC = () => {
  const pathname = window.location.pathname;
  const map: Record<string, { title: string; path: string; key?: string; columns: ColumnsType<AdminRow> }> = { requests: { title: 'Payment requests', path: '/admin/requests', columns: [{ title: 'Request', dataIndex: 'id' }, { title: 'Requester', dataIndex: 'requester_handle' }, { title: 'Payer', dataIndex: 'payer_handle' }, { title: 'Amount', render: (_, record) => `${record.amount || '-'} ${record.currency || ''}` }, { title: 'Status', dataIndex: 'status', render: (value) => <Tag color={colors[value]}>{value}</Tag> }] }, splits: { title: 'Bill splits', path: '/admin/splits', columns: [{ title: 'Split', dataIndex: 'id' }, { title: 'Creator', dataIndex: 'creator_handle' }, { title: 'Amount', render: (_, record) => `${record.total_amount || '-'} ${record.currency || ''}` }, { title: 'Participants', render: (_, record) => Array.isArray(record.participants) ? record.participants.length : 0 }, { title: 'Status', dataIndex: 'status', render: (value) => <Tag color={colors[value]}>{value}</Tag> }] }, attempts: { title: 'Transfer attempts', path: '/admin/transfer-attempts', columns: [{ title: 'User', dataIndex: 'user', render: text }, { title: 'Reason', dataIndex: 'rejection_reason' }, { title: 'Created', dataIndex: 'created_at', render: date }] }, audit: { title: 'Audit trail', path: '/admin/audit-log', columns: [{ title: 'Actor', dataIndex: 'user', render: text }, { title: 'Action', dataIndex: 'action' }, { title: 'Metadata', dataIndex: 'metadata', render: text }, { title: 'When', dataIndex: 'created_at', render: date }] }, settings: { title: 'Platform settings', path: '/admin/settings', columns: [{ title: 'Key', dataIndex: 'key' }, { title: 'Value', dataIndex: 'value' }, { title: 'Updated', dataIndex: 'updated_at', render: date }] }, team: { title: 'Admin team', path: '/admin/team', key: 'team_members', columns: [{ title: 'Username', dataIndex: 'username' }, { title: 'Email', dataIndex: 'email' }, { title: 'Staff', dataIndex: 'is_staff' }] }, disputes: { title: 'Disputes', path: '/admin/disputes', columns: [{ title: 'Dispute', dataIndex: 'id' }, { title: 'User', dataIndex: 'user', render: text }, { title: 'Reason', dataIndex: 'reason' }, { title: 'Status', dataIndex: 'status', render: (value) => <Tag color={colors[value]}>{value}</Tag> }] } };
  const config = Object.entries(map).find(([key]) => pathname.includes(`/${key}`))?.[1] || map.requests; const query = useQuery({ queryKey: ['admin-records-page', config.path], queryFn: () => adminRequest<unknown>(config.path) }); const data = query.data as Record<string, unknown> | undefined; const rows = Array.isArray(query.data) ? query.data as AdminRow[] : (data?.results || data?.[config.key || ''] || []) as AdminRow[];
  return <PageContainer className="admin-page" title={config.title} subTitle="Operational records from the wallet administration API."><Card><RecordsTable rows={rows} loading={query.isLoading} onView={(row) => Modal.info({ title: `${config.title} details`, content: <ReadableValue value={row} />, width: 760 })} columns={config.columns} /></Card></PageContainer>;
};
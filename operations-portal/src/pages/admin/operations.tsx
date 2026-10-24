import { ReloadOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { App, Alert, Button, Card, Col, DatePicker, Descriptions, Form, Input, InputNumber, Row, Select, Space, Statistic, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import React from 'react';
import { adminRequest } from '@/services/admin';

type AdminRecord = { id?: number | string; [key: string]: unknown };
type Payload = Record<string, unknown>;

const records = (payload: unknown, key: string): AdminRecord[] => {
  if (!payload || typeof payload !== 'object') return [];
  const value = (payload as Payload)[key];
  return Array.isArray(value) ? value as AdminRecord[] : [];
};
const text = (value: unknown) => value === null || value === undefined || value === '' ? '—' : String(value);
const value = (payload: unknown, key: string): string | number => {
  if (!payload || typeof payload !== 'object') return '—';
  const result = (payload as Payload)[key];
  return typeof result === 'string' || typeof result === 'number' ? result : '—';
};
const columns = (fields: string[]): ColumnsType<AdminRecord> => fields.map((field) => ({
  title: field.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase()),
  dataIndex: field,
  render: (cell: unknown) => field === 'status' || field === 'severity' || field === 'alert_type'
    ? <Tag>{text(cell)}</Tag>
    : <Typography.Text>{typeof cell === 'object' && cell !== null ? JSON.stringify(cell) : text(cell)}</Typography.Text>,
}));
const timeRangeOptions = ['7d', '30d', '90d', '1y'].map((range) => ({ label: range, value: range }));

const AnalyticsPage: React.FC = () => {
  const [range, setRange] = React.useState('30d');
  const query = useQuery({ queryKey: ['admin-analytics', range], queryFn: () => adminRequest<Payload>(`/admin/analytics?time_range=${range}`) });
  const data = query.data;
  return <PageContainer className="admin-page" title="Analytics" subTitle="Operational counts and transaction activity from the administration API." extra={<Select value={range} options={timeRangeOptions} onChange={setRange} />}>
    {query.isError && <Alert type="error" showIcon message="Analytics could not be loaded." className="resource-toolbar" />}
    <Row gutter={[16, 16]} className="metric-row">
      {[
        ['Total users', value(data, 'total_users')],
        ['Active users', value(data, 'active_users')],
        ['Suspended users', value(data, 'suspended_users')],
        ['Wallets', value(data, 'total_wallets')],
        ['Frozen wallets', value(data, 'frozen_wallets')],
        ['Pending payment requests', value(data, 'pending_payment_requests')],
      ].map(([title, metric]) => <Col xs={24} sm={12} lg={8} key={title}><Card className="metric-card" loading={query.isLoading}><Statistic title={title} value={metric} /></Card></Col>)}
    </Row>
    <Row gutter={[16, 16]} className="overview-grid">
      <Col xs={24} lg={12}><Card title="Completed transaction counts"><Table rowKey="date" size="small" pagination={false} loading={query.isLoading} dataSource={records(data, 'transactions_trend')} columns={columns(['date', 'value'])} /></Card></Col>
      <Col xs={24} lg={12}><Card title="New user counts"><Table rowKey="date" size="small" pagination={false} loading={query.isLoading} dataSource={records(data, 'users_trend')} columns={columns(['date', 'value'])} /></Card></Col>
    </Row>
    <Alert className="resource-toolbar" type="info" showIcon message="The API does not segment transaction volumes and fees by currency. This view intentionally omits cross-currency totals." />
  </PageContainer>;
};

const SettlementsPage: React.FC = () => {
  const [range, setRange] = React.useState('30d');
  const [status, setStatus] = React.useState('');
  const query = useQuery({ queryKey: ['admin-settlements', range, status], queryFn: () => adminRequest<Payload>(`/admin/settlements?date_range=${range}${status ? `&status=${encodeURIComponent(status)}` : ''}`) });
  return <PageContainer className="admin-page" title="Settlements" subTitle="Review settlement records and current processing states." extra={<Space><Select value={range} options={timeRangeOptions} onChange={setRange} /><Select allowClear placeholder="All statuses" value={status || undefined} options={['pending', 'processing', 'completed', 'failed'].map((item) => ({ value: item, label: item }))} onChange={(item) => setStatus(item || '')} /></Space>}>
    {query.isError && <Alert type="error" showIcon message="Settlement data could not be loaded." className="resource-toolbar" />}
    <Card><Table rowKey="id" loading={query.isLoading} dataSource={records(query.data, 'settlements')} columns={columns(['id', 'merchant_name', 'amount', 'currency', 'fee_amount', 'net_amount', 'status', 'created_at'])} pagination={{ pageSize: 20, showSizeChanger: true }} scroll={{ x: 1000 }} /></Card>
    <Alert className="resource-toolbar" type="info" showIcon message="Settlement processing and payout controls are not exposed by the current administration API." />
  </PageContainer>;
};

const ReportsPage: React.FC = () => {
  const query = useQuery({ queryKey: ['admin-reports'], queryFn: () => adminRequest<Payload>('/admin/reports') });
  const report = records(query.data, 'reports')[0];
  const metrics = report && typeof report.metrics === 'object' && report.metrics !== null ? report.metrics as Payload : {};
  return <PageContainer className="admin-page" title="Reports" subTitle="Read-only summary calculated by the backend for the current month." extra={<Button icon={<ReloadOutlined />} onClick={() => query.refetch()}>Refresh</Button>}>
    <Alert type="warning" showIcon className="resource-toolbar" message="Report export and generation are not implemented. This screen displays the backend's current-month summary only; amounts are not currency-segmented." />
    {query.isError && <Alert type="error" showIcon message="Report data could not be loaded." className="resource-toolbar" />}
    {report ? <Card title={text(report.name)}><Descriptions bordered column={{ xs: 1, sm: 2 }} items={Object.entries(metrics).map(([key, metric]) => ({ key, label: key.replaceAll('_', ' '), children: text(metric) }))} /></Card> : <Card loading={query.isLoading}>No report summary is available.</Card>}
  </PageContainer>;
};

const FeeRevenuePage: React.FC = () => {
  const [range, setRange] = React.useState('30d');
  const query = useQuery({ queryKey: ['admin-fee-revenue', range], queryFn: () => adminRequest<Payload>(`/admin/fee-revenue?time_range=${range}`) });
  return <PageContainer className="admin-page" title="Fee revenue" subTitle="Completed transactions grouped by currency for the selected reporting period." extra={<Select value={range} options={timeRangeOptions} onChange={setRange} />}>
    {query.isError && <Alert type="error" showIcon message="Fee revenue could not be loaded." className="resource-toolbar" />}
    <Card title="Currency breakdown"><Table rowKey="currency" loading={query.isLoading} dataSource={records(query.data, 'currencies')} columns={columns(['currency', 'total', 'count'])} pagination={false} /></Card>
    <Alert className="resource-toolbar" type="info" showIcon message="The backend's overall fee total and daily trend combine currencies. They are intentionally not presented as a single monetary amount." />
  </PageContainer>;
};

const SystemHealthPage: React.FC = () => {
  const query = useQuery({ queryKey: ['admin-system-health'], queryFn: () => adminRequest<Payload>('/admin/system/health'), refetchInterval: 30_000 });
  const data = query.data;
  const healthItems = ['api_status', 'database_status', 'uptime', 'active_connections', 'cpu_usage', 'memory_usage', 'disk_usage', 'recent_transactions', 'pending_transactions', 'total_users', 'total_wallets'];
  return <PageContainer className="admin-page" title="System health" subTitle="Live operational measurements. Refreshes automatically every 30 seconds." extra={<Button icon={<ReloadOutlined />} onClick={() => query.refetch()}>Refresh</Button>}>
    {query.isError && <Alert type="error" showIcon message="Health metrics could not be loaded." className="resource-toolbar" />}
    <Card loading={query.isLoading} title="Measured status"><Descriptions bordered column={{ xs: 1, sm: 2, lg: 3 }} items={healthItems.map((key) => ({ key, label: key.replaceAll('_', ' '), children: text(data?.[key]) }))} /></Card>
    <Alert className="resource-toolbar" type="warning" showIcon message="Response time and cache status returned by the current API are hard-coded and are omitted. This page is monitoring only; it does not restart services or run database maintenance." />
  </PageContainer>;
};

const AlertRulesPage: React.FC = () => {
  const { message, modal } = App.useApp();
  const client = useQueryClient();
  const [form] = Form.useForm();
  const query = useQuery({ queryKey: ['admin-alert-rules'], queryFn: () => adminRequest<Payload>('/admin/alerts/rules') });
  const createRule = async (values: Payload) => {
    try {
      await adminRequest('/admin/alerts/rules', { method: 'POST', data: values });
      message.success('Alert rule saved.');
      form.resetFields();
      await client.invalidateQueries({ queryKey: ['admin-alert-rules'] });
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Alert rule could not be saved.');
    }
  };
  const deleteRule = (id: unknown) => {
    modal.confirm({
      title: 'Delete this alert rule?',
      content: 'This removes the rule and its associated alert-event history.',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await adminRequest(`/admin/alerts/rules?rule_id=${encodeURIComponent(String(id))}`, { method: 'DELETE' });
          message.success('Alert rule deleted.');
          await client.invalidateQueries({ queryKey: ['admin-alert-rules'] });
        } catch (error) {
          message.error(error instanceof Error ? error.message : 'Alert rule could not be deleted.');
          throw error;
        }
      },
    });
  };
  const ruleColumns: ColumnsType<AdminRecord> = [
    ...columns(['name', 'alert_type', 'condition', 'threshold', 'channels', 'enabled', 'trigger_count']),
    { title: 'Actions', render: (_, row) => <Button danger type="link" onClick={() => deleteRule(row.id)}>Delete</Button> },
  ];
  return <PageContainer className="admin-page" title="Alert rules" subTitle="Create and review alert rule records." extra={<Button icon={<ReloadOutlined />} onClick={() => query.refetch()}>Refresh</Button>}>
    <Alert className="resource-toolbar" type="warning" showIcon message="The API stores alert-rule definitions but does not expose a rule-update or alert-event resolution action. Do not rely on these records as active delivery monitoring." />
    {query.isError && <Alert type="error" showIcon message="Alert rules could not be loaded." className="resource-toolbar" />}
    <Card title="Create alert rule" className="resource-toolbar">
      <Form form={form} layout="vertical" onFinish={createRule}>
        <Row gutter={16}>
          <Col xs={24} md={8}><Form.Item name="name" label="Name" rules={[{ required: true }]}><Input maxLength={100} /></Form.Item></Col>
          <Col xs={24} md={8}><Form.Item name="alert_type" label="Severity" initialValue="warning"><Select options={['info', 'warning', 'critical'].map((item) => ({ label: item, value: item }))} /></Form.Item></Col>
          <Col xs={24} md={8}><Form.Item name="threshold" label="Threshold" rules={[{ required: true }]}><Input maxLength={100} /></Form.Item></Col>
          <Col xs={24}><Form.Item name="description" label="Description"><Input /></Form.Item></Col>
          <Col xs={24} md={12}><Form.Item name="condition" label="Condition expression" rules={[{ required: true }]}><Input /></Form.Item></Col>
          <Col xs={24} md={12}><Form.Item name="channels" label="Notification channels"><Select mode="multiple" options={['email', 'webhook', 'sms', 'slack'].map((item) => ({ label: item, value: item }))} /></Form.Item></Col>
        </Row>
        <Button type="primary" htmlType="submit" loading={query.isFetching}>Save rule</Button>
      </Form>
    </Card>
    <Card title="Configured rules"><Table rowKey="id" loading={query.isLoading} dataSource={records(query.data, 'rules')} columns={ruleColumns} pagination={{ pageSize: 15 }} scroll={{ x: 1000 }} /></Card>
  </PageContainer>;
};

const CommunicationsPage: React.FC = () => {
  const query = useQuery({ queryKey: ['admin-communications'], queryFn: () => adminRequest<Payload>('/admin/communications') });
  return <PageContainer className="admin-page" title="Communications log" subTitle="Review admin message records." extra={<Button icon={<ReloadOutlined />} onClick={() => query.refetch()}>Refresh</Button>}>
    <Alert className="resource-toolbar" type="warning" showIcon message="The current backend records message intent but does not deliver email, push, or in-app notifications. Sending controls are intentionally withheld." />
    {query.isError && <Alert type="error" showIcon message="Message records could not be loaded." className="resource-toolbar" />}
    <Card><Table rowKey="id" loading={query.isLoading} dataSource={records(query.data, 'messages')} columns={columns(['id', 'recipient', 'sender', 'subject', 'content', 'status', 'delivery_error', 'created_at'])} pagination={{ pageSize: 20 }} scroll={{ x: 1200 }} /></Card>
  </PageContainer>;
};

const FeeWaiversPage: React.FC = () => {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [saving, setSaving] = React.useState(false);
  const createWaiver = async (values: Payload) => {
    setSaving(true);
    try {
      const body = {
        ...values,
        valid_from: values.valid_from && typeof values.valid_from === 'object' && 'toISOString' in values.valid_from
          ? (values.valid_from as { toISOString: () => string }).toISOString()
          : values.valid_from,
        valid_until: values.valid_until && typeof values.valid_until === 'object' && 'toISOString' in values.valid_until
          ? (values.valid_until as { toISOString: () => string }).toISOString()
          : values.valid_until,
      };
      const result = await adminRequest<AdminRecord>('/admin/finance/fee-waivers', { method: 'POST', data: body });
      message.success(`Fee waiver ${String(result.id || '')} created.`);
      form.resetFields();
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Fee waiver could not be created.');
    } finally {
      setSaving(false);
    }
  };
  return <PageContainer className="admin-page" title="Fee waivers" subTitle="Grant a time-bounded fee waiver to an identified user." >
    <Alert className="resource-toolbar" type="warning" showIcon message="The backend supports granting waivers but does not expose a waiver-list, edit, or revoke endpoint. Validate the user and approved duration before creating one." />
    <Card title="Create fee waiver">
      <Form form={form} layout="vertical" onFinish={createWaiver}>
        <Row gutter={16}>
          <Col xs={24} md={12}><Form.Item name="user" label="User ID" rules={[{ required: true }]}><InputNumber min={1} precision={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col xs={24} md={12}><Form.Item name="applies_to" label="Applies to" rules={[{ required: true }]}><Select options={[{ value: 'p2p_transfer', label: 'P2P transfer' }, { value: 'merchant_transfer', label: 'Merchant transfer' }]} /></Form.Item></Col>
          <Col xs={24} md={12}><Form.Item name="valid_from" label="Valid from" rules={[{ required: true }]}><DatePicker showTime style={{ width: '100%' }} /></Form.Item></Col>
          <Col xs={24} md={12}><Form.Item name="valid_until" label="Valid until"><DatePicker showTime style={{ width: '100%' }} /></Form.Item></Col>
          <Col xs={24}><Form.Item name="reason" label="Reason" rules={[{ required: true, whitespace: true }]}><Input.TextArea maxLength={1000} showCount /></Form.Item></Col>
        </Row>
        <Button type="primary" htmlType="submit" loading={saving}>Create waiver</Button>
      </Form>
    </Card>
  </PageContainer>;
};

export const OperationsPage: React.FC = () => {
  const path = window.location.pathname;
  if (path.includes('analytics')) return <AnalyticsPage />;
  if (path.includes('settlements')) return <SettlementsPage />;
  if (path.includes('reports')) return <ReportsPage />;
  if (path.includes('fee-revenue')) return <FeeRevenuePage />;
  if (path.includes('system-health')) return <SystemHealthPage />;
  if (path.includes('alerts')) return <AlertRulesPage />;
  if (path.includes('communications')) return <CommunicationsPage />;
  if (path.includes('fee-waivers')) return <FeeWaiversPage />;
  return <PageContainer className="admin-page" title="Operations"><Alert type="error" showIcon message="Unknown operations page." /></PageContainer>;
};

export default OperationsPage;
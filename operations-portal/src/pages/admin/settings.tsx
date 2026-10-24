import { ReloadOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { App, Alert, Button, Card, Drawer, Form, Input, Space, Table, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import React from 'react';
import { adminRequest } from '@/services/admin';

type Setting = { key: string; value: string; description?: string; updated_at?: string };

const SettingsPage: React.FC = () => {
  const { message, modal } = App.useApp();
  const client = useQueryClient();
  const [selected, setSelected] = React.useState<Setting | null>(null);
  const [form] = Form.useForm<{ value: string; reason: string }>();
  const query = useQuery({ queryKey: ['admin-settings'], queryFn: () => adminRequest<Setting[]>('/admin/settings') });
  const save = async (values: { value: string; reason: string }) => {
    if (!selected) return;
    modal.confirm({
      title: 'Save platform setting?',
      content: `Change "${selected.key}"? This will be recorded in the audit trail.`,
      onOk: async () => {
        try {
          await adminRequest(`/admin/settings/${encodeURIComponent(selected.key)}`, { method: 'PATCH', data: values });
          message.success('Setting updated.');
          setSelected(null);
          await client.invalidateQueries({ queryKey: ['admin-settings'] });
        } catch (error) {
          message.error(error instanceof Error ? error.message : 'The setting could not be updated.');
          throw error;
        }
      },
    });
  };
  const columns: ColumnsType<Setting> = [
    { title: 'Key', dataIndex: 'key', render: (key: string) => <Typography.Text code>{key}</Typography.Text> },
    { title: 'Value', dataIndex: 'value', ellipsis: true },
    { title: 'Description', dataIndex: 'description' },
    { title: 'Last updated', dataIndex: 'updated_at', render: (date?: string) => date ? new Date(date).toLocaleString() : '—' },
    { title: 'Action', render: (_, setting) => <Button type="link" onClick={() => { setSelected(setting); form.setFieldsValue({ value: setting.value, reason: '' }); }}>Edit</Button> },
  ];
  return <PageContainer className="admin-page" title="Platform settings" subTitle="Review and update runtime configuration. Changes are audit logged." extra={<Button icon={<ReloadOutlined />} onClick={() => query.refetch()}>Refresh</Button>}>
    <Alert className="resource-toolbar" type="warning" showIcon message="Only change settings with an approved operational reason. A setting change can affect transaction processing and user access." />
    {query.isError && <Alert className="resource-toolbar" type="error" showIcon message="Platform settings could not be loaded." />}
    <Card><Table rowKey="key" loading={query.isLoading} dataSource={query.data || []} columns={columns} pagination={{ pageSize: 20 }} /></Card>
    <Drawer title={selected ? `Edit ${selected.key}` : 'Edit setting'} open={Boolean(selected)} onClose={() => setSelected(null)} width={480}>
      {selected && <Form form={form} layout="vertical" onFinish={save}>
        <Typography.Paragraph type="secondary">{selected.description || 'No description provided.'}</Typography.Paragraph>
        <Form.Item name="value" label="Value" rules={[{ required: true, message: 'Enter a value.' }]}><Input.TextArea autoSize={{ minRows: 3, maxRows: 8 }} /></Form.Item>
        <Form.Item name="reason" label="Reason for change" rules={[{ required: true, whitespace: true, message: 'An audit reason is required.' }]}><Input.TextArea maxLength={500} showCount /></Form.Item>
        <Space><Button onClick={() => setSelected(null)}>Cancel</Button><Button type="primary" htmlType="submit">Save setting</Button></Space>
      </Form>}
    </Drawer>
  </PageContainer>;
};

export default SettingsPage;

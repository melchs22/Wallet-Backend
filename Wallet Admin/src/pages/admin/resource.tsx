import { CheckOutlined, EyeOutlined, PlayCircleOutlined, ReloadOutlined, SearchOutlined, StopOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { App, Button, Card, Descriptions, Drawer, Empty, Input, Modal, Select, Space, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useLocation } from '@umijs/max';
import dayjs from 'dayjs';
import React, { useState } from 'react';
import { adminRequest, getAdminResourceConfig, type AdminResourceConfig, type AdminRow } from '@/services/admin';
import './style.css';

const formatValue = (value: unknown) => {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
};

const formatDate = (value: unknown) => {
  if (!value) return '-';
  const parsed = dayjs(String(value));
  return parsed.isValid() ? parsed.format('DD MMM YYYY, HH:mm') : formatValue(value);
};

const ResourcePage: React.FC = () => {
  const { pathname } = useLocation();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const config = getAdminResourceConfig(pathname);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('');
  const [selected, setSelected] = useState<AdminRow | null>(null);
  const query = useQuery({
    queryKey: ['admin-resource', config.key, search, filter],
    queryFn: () => adminRequest<unknown>(config.path, { params: { query: search, status: filter } }),
  });
  const rows = config.extract(query.data);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['admin-resource', config.key] });
  const execute = async (action: { label: string; method: string; path: (row: AdminRow) => string; confirm?: string }, row: AdminRow) => {
    try {
      await adminRequest(action.path(row), { method: action.method, data: {} });
      message.success(`${action.label} completed`);
      refresh();
    } catch {
      message.error(`${action.label} could not be completed`);
    }
  };
  const columns: ColumnsType<AdminRow> = config.columns.map((column) => ({
    title: column.label,
    dataIndex: column.key,
    key: column.key,
    ellipsis: true,
    render: (value: unknown) => column.date ? formatDate(value) : column.status ? <Tag color={column.statusColors?.[String(value)] || 'default'}>{formatValue(value)}</Tag> : formatValue(value),
  }));
  columns.push({ title: 'Actions', key: 'actions', fixed: 'right', render: (_, row) => <Space><Button type="link" icon={<EyeOutlined />} onClick={() => setSelected(row)}>View</Button>{config.actions?.map((action) => <Button key={action.label} type="link" icon={action.icon === 'play' ? <PlayCircleOutlined /> : action.icon === 'check' ? <CheckOutlined /> : <StopOutlined />} onClick={() => Modal.confirm({ title: action.label, content: action.confirm, onOk: () => execute(action, row) })}>{action.label}</Button>)}</Space> });

  return <PageContainer className="admin-page" title={config.title} subTitle={config.description} extra={<Button icon={<ReloadOutlined />} onClick={refresh}>Refresh</Button>}>
    <Card className="resource-toolbar"><Space wrap><Input allowClear prefix={<SearchOutlined />} value={search} onChange={(event) => setSearch(event.target.value)} placeholder={config.searchPlaceholder || 'Search records'} style={{ width: 280 }} />{config.filters && <Select allowClear value={filter || undefined} onChange={(value) => setFilter(value || '')} placeholder="Filter status" options={config.filters.map((value) => ({ value, label: value }))} style={{ width: 160 }} />}</Space></Card>
    <Card><Table rowKey={(row) => String(row.id || row.key)} loading={query.isLoading} dataSource={rows} columns={columns} scroll={{ x: 1000 }} pagination={{ pageSize: 15, showSizeChanger: true }} locale={{ emptyText: query.isError ? 'Unable to load this resource' : <Empty description="No records found" /> }} /></Card>
    <Drawer title={config.detailTitle || 'Record details'} open={Boolean(selected)} onClose={() => setSelected(null)} width={520}>{selected ? <Descriptions bordered column={1} items={Object.entries(selected).map(([key, value]) => ({ label: key.replaceAll('_', ' '), children: formatValue(value) }))} /> : <Empty />}</Drawer>
  </PageContainer>;
};

export default ResourcePage;
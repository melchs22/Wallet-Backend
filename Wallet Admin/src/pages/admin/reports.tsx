import { DownloadOutlined, FileTextOutlined, ReloadOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Button, Card, Col, Row, Statistic, Table, Tag } from 'antd';
import React from 'react';
import dayjs from 'dayjs';
import { getDashboard, getTransactions, type AdminTransaction } from '@/services/admin';

const ReportsPage: React.FC = () => {
  const dashboard = useQuery({ queryKey: ['admin-reports-dashboard'], queryFn: getDashboard });
  const transactions = useQuery({ queryKey: ['admin-reports-transactions'], queryFn: () => getTransactions({ page_size: 100 }) });
  const rows = transactions.data?.results || [];
  const exportCsv = () => {
    const header = ['Reference', 'Type', 'Sender', 'Recipient', 'Amount', 'Currency', 'Status', 'Created'];
    const body = rows.map((row: AdminTransaction) => [row.id, row.type, row.sender_handle || row.sender, row.recipient_handle || row.recipient, row.amount, row.currency, row.status, row.created_at]);
    const csv = [header, ...body].map((line) => line.map((value) => `"${String(value ?? '').replaceAll('"', '""')}"`).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = `dsd-admin-transactions-${dayjs().format('YYYY-MM-DD')}.csv`; link.click(); URL.revokeObjectURL(url);
  };
  return <PageContainer title="Financial reports" subTitle="Live operational reporting from the wallet ledger." extra={<Button icon={<ReloadOutlined />} onClick={() => { dashboard.refetch(); transactions.refetch(); }}>Refresh</Button>}>
    <Row gutter={[16, 16]}><Col xs={24} sm={12} lg={6}><Card><Statistic title="Users" value={dashboard.data?.total_users || 0} /></Card></Col><Col xs={24} sm={12} lg={6}><Card><Statistic title="Wallets" value={dashboard.data?.total_wallets || 0} /></Card></Col><Col xs={24} sm={12} lg={6}><Card><Statistic title="P2P today" value={dashboard.data?.p2p_volume_today || '0'} suffix="GNF" /></Card></Col><Col xs={24} sm={12} lg={6}><Card><Statistic title="Pending requests" value={dashboard.data?.pending_payment_requests || 0} /></Card></Col></Row>
    <Card className="mt-6" title={<span><FileTextOutlined /> Transaction export</span>} extra={<Button type="primary" icon={<DownloadOutlined />} disabled={!rows.length} onClick={exportCsv}>Export CSV</Button>}><Table rowKey="id" loading={transactions.isLoading} dataSource={rows} pagination={{ pageSize: 15 }} scroll={{ x: 900 }} columns={[{ title: 'Reference', dataIndex: 'id' }, { title: 'Type', dataIndex: 'type' }, { title: 'Sender', render: (_, row: AdminTransaction) => row.sender_handle || String(row.sender || '-') }, { title: 'Recipient', render: (_, row: AdminTransaction) => row.recipient_handle || String(row.recipient || '-') }, { title: 'Amount', render: (_, row: AdminTransaction) => `${row.amount || '-'} ${row.currency || ''}` }, { title: 'Status', dataIndex: 'status', render: (value: string) => <Tag>{value}</Tag> }, { title: 'Created', dataIndex: 'created_at' }]} /></Card>
  </PageContainer>;
};

export default ReportsPage;
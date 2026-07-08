import { useEffect, useState } from 'react'
import { Card, Row, Col, Statistic, Progress, Tag, Button, Spin, Select, Space, message } from 'antd'
import {
  UserOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
  PushpinOutlined,
  GlobalOutlined,
} from '@ant-design/icons'
import { apiFetch } from '@/lib/utils'

const PLATFORM_COLORS: Record<string, string> = {
  chatgpt: '#3b82f6',
  cursor: '#10b981',
}

const STATUS_COLORS: Record<string, string> = {
  registered: 'default',
  trial: 'success',
  subscribed: 'success',
  expired: 'warning',
  invalid: 'error',
}

export default function Dashboard() {
  const [stats, setStats] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [proxies, setProxies] = useState<any[]>([])
  const [pinnedMode, setPinnedMode] = useState<'auto' | 'select' | 'custom'>('auto')
  const [pinnedProxyId, setPinnedProxyId] = useState<number | null>(null)
  const [pinnedResolvedUrl, setPinnedResolvedUrl] = useState('')
  const [pinSaving, setPinSaving] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const data = await apiFetch('/accounts/stats')
      setStats(data)
    } finally {
      setLoading(false)
    }
  }

  const loadProxies = async () => {
    try {
      const [proxyData, pinnedData] = await Promise.all([
        apiFetch('/proxies'),
        apiFetch('/proxies/pinned'),
      ])
      setProxies(proxyData || [])
      setPinnedMode(pinnedData.mode || 'auto')
      setPinnedProxyId(pinnedData.proxy_id ?? null)
      setPinnedResolvedUrl(pinnedData.resolved_url || '')
    } catch {
      // ignore
    }
  }

  const quickPin = async (mode: 'auto' | 'select', proxyId?: number | null) => {
    setPinSaving(true)
    try {
      const body: any = { mode }
      if (mode === 'select') body.proxy_id = proxyId ?? pinnedProxyId
      const data = await apiFetch('/proxies/pinned', {
        method: 'POST',
        body: JSON.stringify(body),
      })
      setPinnedMode(data.mode || 'auto')
      setPinnedProxyId(data.proxy_id ?? null)
      setPinnedResolvedUrl(data.resolved_url || '')
      message.success(
        mode === 'auto' ? 'Proxy set to Auto (random)' : `Pinned to: ${data.resolved_url}`
      )
    } catch (e: any) {
      message.error(`Failed: ${e.message}`)
    } finally {
      setPinSaving(false)
    }
  }

  useEffect(() => {
    load()
    loadProxies()
  }, [])

  const statCards = [
    {
      title: 'Total Accounts',
      value: stats?.total ?? 0,
      icon: <UserOutlined style={{ fontSize: 32 }} />,
      color: '#6366f1',
    },
    {
      title: 'Trial',
      value: stats?.by_status?.trial ?? 0,
      icon: <ClockCircleOutlined style={{ fontSize: 32 }} />,
      color: '#f59e0b',
    },
    {
      title: 'Subscribed',
      value: stats?.by_status?.subscribed ?? 0,
      icon: <CheckCircleOutlined style={{ fontSize: 32 }} />,
      color: '#10b981',
    },
    {
      title: 'Expired/Invalid',
      value: (stats?.by_status?.expired ?? 0) + (stats?.by_status?.invalid ?? 0),
      icon: <CloseCircleOutlined style={{ fontSize: 32 }} />,
      color: '#ef4444',
    },
  ]

  return (
    <div style={{ padding: 0 }}>
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 'bold', margin: 0 }}>Dashboard</h1>
          <p style={{ color: '#7a8ba3', marginTop: 4 }}>Account Overview</p>
        </div>
        <Space>
          {/* Quick proxy selection dropdown */}
          <Select
            style={{ width: 280 }}
            loading={pinSaving}
            value={pinnedMode === 'auto' ? '__auto__' : pinnedMode === 'select' ? pinnedProxyId : '__custom__'}
            onChange={(val) => {
              if (val === '__auto__') {
                setPinnedMode('auto')
                quickPin('auto')
              } else if (val === '__custom__') {
                // Redirect to proxies page for custom URL entry
                message.info('Custom proxy URL can be set on the Proxies page')
              } else if (typeof val === 'number') {
                setPinnedMode('select')
                setPinnedProxyId(val)
                quickPin('select', val)
              }
            }}
            options={[
              { value: '__auto__', label: <Space><GlobalOutlined /> Auto (Random Proxy)</Space> },
              ...(pinnedResolvedUrl && pinnedMode === 'custom'
                ? [{ value: '__custom__', label: <Space><PushpinOutlined /> Custom: {pinnedResolvedUrl.slice(0, 30)}...</Space> }]
                : []),
              { value: '__divider__', label: '─── Select from Pool ───', disabled: true },
              ...proxies.map((p) => ({
                value: p.id,
                label: (
                  <Space>
                    <PushpinOutlined style={{ color: p.id === pinnedProxyId ? '#1677ff' : undefined }} />
                    <span style={{ fontFamily: 'monospace', fontSize: 11 }}>
                      {p.url.length > 35 ? p.url.slice(0, 35) + '...' : p.url}
                    </span>
                    {p.region && <Tag style={{ fontSize: 10, lineHeight: '16px', margin: 0 }}>{p.region}</Tag>}
                    {p.is_active ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <CloseCircleOutlined style={{ color: '#ff4d4f' }} />}
                  </Space>
                ),
              })),
            ]}
            placeholder="Select proxy for next run"
            showSearch
            optionFilterProp="label"
          />
          <Button icon={<ReloadOutlined spin={loading} />} onClick={load} loading={loading}>
            Refresh
          </Button>
        </Space>
      </div>

      <Row gutter={[16, 16]}>
        {statCards.map(({ title, value, icon, color }) => (
          <Col xs={24} sm={12} lg={6} key={title}>
            <Card>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Statistic title={title} value={value} />
                <div style={{ color, opacity: 0.8 }}>{icon}</div>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="Platform Distribution">
            {loading ? (
              <div style={{ textAlign: 'center', padding: 40 }}>
                <Spin />
              </div>
            ) : stats ? (
              Object.entries(stats.by_platform || {}).map(([platform, count]: any) => (
                <div key={platform} style={{ marginBottom: 16 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <Tag color={PLATFORM_COLORS[platform] || 'default'}>{platform}</Tag>
                    <span>{count}</span>
                  </div>
                  <Progress
                    percent={stats.total ? Math.round((count / stats.total) * 100) : 0}
                    strokeColor={PLATFORM_COLORS[platform] || '#6366f1'}
                    showInfo={false}
                  />
                </div>
              ))
            ) : (
              <div style={{ textAlign: 'center', color: '#7a8ba3' }}>Loading...</div>
            )}
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card title="Status Distribution">
            {loading ? (
              <div style={{ textAlign: 'center', padding: 40 }}>
                <Spin />
              </div>
            ) : stats ? (
              Object.entries(stats.by_status || {}).map(([status, count]: any) => (
                <div
                  key={status}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '8px 0',
                    borderBottom: '1px solid rgba(255,255,255,0.1)',
                  }}
                >
                  <Tag color={STATUS_COLORS[status] || 'default'}>{status}</Tag>
                  <span>{count}</span>
                </div>
              ))
            ) : (
              <div style={{ textAlign: 'center', color: '#7a8ba3' }}>Loading...</div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

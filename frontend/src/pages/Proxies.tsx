import { useEffect, useState, type Key } from 'react'
import { Card, Table, Button, Input, Tag, Space, Popconfirm, message, Modal, Select, Radio, Tooltip } from 'antd'
import {
  PlusOutlined,
  DeleteOutlined,
  ReloadOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  SwapRightOutlined,
  SwapLeftOutlined,
  SyncOutlined,
  PushpinOutlined,
  GlobalOutlined,
} from '@ant-design/icons'
import { apiFetch } from '@/lib/utils'

export default function Proxies() {
  const [proxies, setProxies] = useState<any[]>([])
  const [newProxy, setNewProxy] = useState('')
  const [region, setRegion] = useState('')
  const [checking, setChecking] = useState(false)
  const [scraping, setScraping] = useState(false)
  const [loading, setLoading] = useState(false)
  const [selectedRowKeys, setSelectedRowKeys] = useState<Key[]>([])

  // Pinned proxy state
  const [pinnedMode, setPinnedMode] = useState<'auto' | 'select' | 'custom'>('auto')
  const [pinnedProxyId, setPinnedProxyId] = useState<number | null>(null)
  const [pinnedCustomUrl, setPinnedCustomUrl] = useState('')
  const [pinnedResolvedUrl, setPinnedResolvedUrl] = useState('')
  const [pinSaving, setPinSaving] = useState(false)

  const loadPinned = async () => {
    try {
      const data = await apiFetch('/proxies/pinned')
      setPinnedMode(data.mode || 'auto')
      setPinnedProxyId(data.proxy_id ?? null)
      setPinnedCustomUrl(data.custom_url || '')
      setPinnedResolvedUrl(data.resolved_url || '')
    } catch {
      // ignore
    }
  }

  const savePinned = async (mode: 'auto' | 'select' | 'custom', proxyId?: number | null, customUrl?: string) => {
    setPinSaving(true)
    try {
      const body: any = { mode }
      if (mode === 'select') body.proxy_id = proxyId ?? pinnedProxyId
      if (mode === 'custom') body.custom_url = customUrl ?? pinnedCustomUrl
      const data = await apiFetch('/proxies/pinned', {
        method: 'POST',
        body: JSON.stringify(body),
      })
      setPinnedMode(data.mode || 'auto')
      setPinnedProxyId(data.proxy_id ?? null)
      setPinnedCustomUrl(data.custom_url || '')
      setPinnedResolvedUrl(data.resolved_url || '')
      message.success(
        mode === 'auto' ? 'Proxy mode set to Auto (random)' :
        mode === 'select' ? `Pinned to proxy #${data.proxy_id}` :
        'Pinned to custom proxy'
      )
    } catch (e: any) {
      message.error(`Failed to set proxy: ${e.message}`)
    } finally {
      setPinSaving(false)
    }
  }

  const load = async () => {
    setLoading(true)
    try {
      const data = await apiFetch('/proxies')
      setProxies(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    loadPinned()
  }, [])

  const add = async () => {
    if (!newProxy.trim()) return
    const lines = newProxy.trim().split('\n').map((l) => l.trim()).filter(Boolean)
    try {
      if (lines.length > 1) {
        await apiFetch('/proxies/bulk', {
          method: 'POST',
          body: JSON.stringify({ proxies: lines, region }),
        })
      } else {
        await apiFetch('/proxies', {
          method: 'POST',
          body: JSON.stringify({ url: lines[0], region }),
        })
      }
      message.success('Added successfully')
      setNewProxy('')
      setRegion('')
      load()
    } catch (e: any) {
      message.error(`Failed to add: ${e.message}`)
    }
  }

  const del = async (id: number) => {
    try {
      await apiFetch(`/proxies/${id}`, { method: 'DELETE' })
      message.success('Deleted successfully')
      setSelectedRowKeys((prev) => prev.filter((key) => key !== id))
      load()
    } catch (e: any) {
      message.error(`Failed to delete: ${e.message || 'Unknown error'}`)
    }
  }

  const batchDel = async () => {
    if (selectedRowKeys.length === 0) return
    const ids = selectedRowKeys.map((key) => Number(key)).filter((v) => Number.isFinite(v))
    try {
      const result = await apiFetch('/proxies/batch-delete', {
        method: 'POST',
        body: JSON.stringify({ ids }),
      }) as { deleted: number; not_found?: number[]; total_requested?: number }
      setSelectedRowKeys([])
      load()

      const notFound = (result.not_found || []) as number[]
      Modal.success({
        title: 'Batch Delete Result',
        okText: 'OK',
        content: (
          <div>
            <div>Requested: {result.total_requested ?? ids.length} items</div>
            <div>Deleted: {result.deleted ?? 0} items</div>
            <div>Not found: {notFound.length} items</div>
            {notFound.length > 0 && (
              <div style={{ marginTop: 8, maxHeight: 120, overflow: 'auto', fontFamily: 'monospace' }}>
                {notFound.join(', ')}
              </div>
            )}
          </div>
        ),
      })
    } catch (e: any) {
      message.error(`Batch delete failed: ${e.message || 'Unknown error'}`)
    }
  }

  const toggle = async (id: number) => {
    await apiFetch(`/proxies/${id}/toggle`, { method: 'PATCH' })
    load()
  }

  const check = async () => {
    setChecking(true)
    try {
      await apiFetch('/proxies/check', { method: 'POST' })
      message.success('Verification task started. Refreshing in 3 seconds...')
      setTimeout(() => {
        load()
        setChecking(false)
      }, 3000)
    } catch (e: any) {
      message.error(e.message || 'Failed to trigger verification')
      setChecking(false)
    }
  }

  const scrape = async () => {
    setScraping(true)
    try {
      await apiFetch('/proxies/scrape', { method: 'POST' })
      message.success('Public proxy scraping task started. Refreshing in 3 seconds...')
      setTimeout(() => {
        load()
        setScraping(false)
      }, 3000)
    } catch (e: any) {
      message.error(e.message || 'Failed to scrape proxies')
      setScraping(false)
    }
  }

  const clearAll = async () => {
    if (!window.confirm('Are you sure you want to delete ALL proxies from the database? This cannot be undone.')) return
    try {
      const res = await apiFetch('/proxies/clear-all', { method: 'POST' })
      message.success(`Cleared database: deleted ${res.deleted} proxies`)
      load()
    } catch (e: any) {
      message.error(e.message || 'Failed to clear proxies')
    }
  }

  const cleanInactive = async () => {
    try {
      const res = await apiFetch('/proxies/delete-inactive', { method: 'POST' })
      message.success(`Cleaned up: deleted ${res.deleted} inactive/failed proxies`)
      load()
    } catch (e: any) {
      message.error(e.message || 'Failed to clean inactive proxies')
    }
  }

  const activeCount = proxies.filter((p) => p.is_active).length
  const inactiveCount = proxies.length - activeCount

  const columns: any[] = [
    {
      title: 'Proxy Address',
      dataIndex: 'url',
      key: 'url',
      render: (text: string) => <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{text}</span>,
    },
    {
      title: 'Region',
      dataIndex: 'region',
      key: 'region',
      filters: [
        { text: 'US Only', value: 'US' },
      ],
      onFilter: (value: any, record: any) => record.region === value,
      render: (text: string) => {
        if (text === 'US') {
          return <Tag color="blue">US</Tag>
        }
        return text ? <Tag>{text}</Tag> : '-'
      },
    },
    {
      title: 'Success/Failed',
      key: 'stats',
      render: (_: any, record: any) => (
        <Space>
          <Tag color="success">{record.success_count}</Tag>
          <span>/</span>
          <Tag color="error">{record.fail_count}</Tag>
        </Space>
      ),
    },
    {
      title: 'Status',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active: boolean) => (
        <Tag color={active ? 'success' : 'error'} icon={active ? <CheckCircleOutlined /> : <CloseCircleOutlined />}>
          {active ? 'Active' : 'Disabled'}
        </Tag>
      ),
    },
    {
      title: 'Actions',
      key: 'action',
      render: (_: any, record: any) => (
        <Space>
          <Button
            type="text"
            size="small"
            icon={record.is_active ? <SwapLeftOutlined /> : <SwapRightOutlined />}
            onClick={() => toggle(record.id)}
          />
          <Popconfirm
            title="Confirm deletion of this proxy?"
            onConfirm={() => del(record.id)}
            okText="Delete"
            cancelText="Cancel"
            okButtonProps={{ danger: true }}
          >
            <Button type="text" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 'bold', margin: 0 }}>Proxy Management</h1>
          <p style={{ color: '#7a8ba3', marginTop: 4 }}>Total {proxies.length} proxies</p>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16 }}>
        <Card size="small">
          <div style={{ color: '#7a8ba3', fontSize: 12 }}>Total Proxies</div>
          <div style={{ fontSize: 24, fontWeight: 'bold', marginTop: 4 }}>{proxies.length}</div>
        </Card>
        <Card size="small">
          <div style={{ color: '#52c41a', fontSize: 12 }}>Active Proxies</div>
          <div style={{ fontSize: 24, fontWeight: 'bold', marginTop: 4, color: '#52c41a' }}>{activeCount}</div>
        </Card>
        <Card size="small">
          <div style={{ color: '#ff4d4f', fontSize: 12 }}>Inactive/Failed</div>
          <div style={{ fontSize: 24, fontWeight: 'bold', marginTop: 4, color: '#ff4d4f' }}>{inactiveCount}</div>
        </Card>
      </div>

      <Card title="Pinned Proxy" extra={<PushpinOutlined />} style={{ borderColor: pinnedMode !== 'auto' ? '#1677ff' : undefined }}>
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Radio.Group
            value={pinnedMode}
            onChange={(e) => {
              const newMode = e.target.value as 'auto' | 'select' | 'custom'
              setPinnedMode(newMode)
              if (newMode === 'auto') savePinned('auto')
            }}
          >
            <Radio.Button value="auto">
              <Tooltip title="Randomly assign proxies from the pool">
                <Space size={4}><GlobalOutlined /> Auto (Random)</Space>
              </Tooltip>
            </Radio.Button>
            <Radio.Button value="select">
              <Tooltip title="Select a specific proxy from the pool">
                <Space size={4}><PushpinOutlined /> Select from Pool</Space>
              </Tooltip>
            </Radio.Button>
            <Radio.Button value="custom">
              <Tooltip title="Enter a custom proxy URL">
                <Space size={4}>Custom URL</Space>
              </Tooltip>
            </Radio.Button>
          </Radio.Group>

          {pinnedMode === 'select' && (
            <Space style={{ width: '100%' }}>
              <Select
                style={{ flex: 1, minWidth: 400 }}
                placeholder="Select a proxy from the pool"
                value={pinnedProxyId ?? undefined}
                onChange={(val) => setPinnedProxyId(val)}
                options={proxies.map((p) => ({
                  value: p.id,
                  label: `${p.url} ${p.region ? `[${p.region}]` : ''} ${p.is_active ? '✓' : '✗'}`,
                }))}
                showSearch
                optionFilterProp="label"
              />
              <Button
                type="primary"
                icon={<PushpinOutlined />}
                loading={pinSaving}
                disabled={!pinnedProxyId}
                onClick={() => savePinned('select', pinnedProxyId)}
              >
                Pin This Proxy
              </Button>
            </Space>
          )}

          {pinnedMode === 'custom' && (
            <Space style={{ width: '100%' }}>
              <Input
                style={{ flex: 1, minWidth: 400 }}
                placeholder="http://user:pass@host:port  or  socks5://host:port"
                value={pinnedCustomUrl}
                onChange={(e) => setPinnedCustomUrl(e.target.value)}
              />
              <Button
                type="primary"
                icon={<PushpinOutlined />}
                loading={pinSaving}
                disabled={!pinnedCustomUrl.trim()}
                onClick={() => savePinned('custom', null, pinnedCustomUrl)}
              >
                Pin This Proxy
              </Button>
            </Space>
          )}

          {pinnedMode !== 'auto' && pinnedResolvedUrl && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Tag color="blue" icon={<PushpinOutlined />}>
                Pinned: {pinnedResolvedUrl}
              </Tag>
              <Button size="small" type="link" onClick={() => savePinned('auto')}>
                Reset to Auto
              </Button>
            </div>
          )}
          {pinnedMode === 'auto' && (
            <div style={{ color: '#7a8ba3', fontSize: 13 }}>
              Proxies are randomly assigned from the pool for each registration run.
            </div>
          )}
        </Space>
      </Card>

      <Card title="Proxy Actions">
        <Space wrap>
          <Button type="primary" icon={<SyncOutlined spin={scraping} />} onClick={scrape} loading={scraping}>
            Scrape Free Proxies
          </Button>
          <Button icon={<ReloadOutlined spin={checking} />} onClick={check} loading={checking}>
            Verify All Proxies
          </Button>
          <Button danger onClick={cleanInactive}>
            Clean Inactive/Failed
          </Button>
          <Button danger type="dashed" onClick={clearAll}>
            Clear Database
          </Button>
        </Space>
      </Card>

      <Card title="Add Proxy (one per line)">
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input.TextArea
            value={newProxy}
            onChange={(e) => setNewProxy(e.target.value)}
            placeholder="http://user:pass@host:port&#10;socks5://host:port"
            rows={3}
            style={{ fontFamily: 'monospace' }}
          />
          <Space>
            <Input
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              placeholder="Region tag (e.g. US, SG)"
              style={{ width: 200 }}
            />
            <Button type="primary" icon={<PlusOutlined />} onClick={add}>
              Add manually
            </Button>
          </Space>
        </Space>
      </Card>

      <Card title="Proxy Database List">
        <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ color: '#7a8ba3' }}>
            Selected {selectedRowKeys.length} items
          </div>
          <Popconfirm
            title={`Confirm deletion of ${selectedRowKeys.length} selected proxies?`}
            onConfirm={batchDel}
            okText="Delete"
            cancelText="Cancel"
            okButtonProps={{ danger: true }}
            disabled={selectedRowKeys.length === 0}
          >
            <Button danger icon={<DeleteOutlined />} disabled={selectedRowKeys.length === 0}>
              Batch Delete
            </Button>
          </Popconfirm>
        </div>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={proxies}
          loading={loading}
          rowSelection={{
            selectedRowKeys,
            onChange: (keys) => setSelectedRowKeys(keys),
          }}
          pagination={{ pageSize: 10, showSizeChanger: true }}
        />
      </Card>
    </div>
  )
}

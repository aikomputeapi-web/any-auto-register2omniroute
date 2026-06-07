import { useEffect, useState } from 'react'
import { Card, Row, Col, Statistic, Progress, Tag, Button, Spin, Input, message } from 'antd'
import {
  UserOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { apiFetch } from '@/lib/utils'

const PLATFORM_COLORS: Record<string, string> = {
  amex: '#006fcf',
  jfcu: '#15803d',
  usbank: '#0c4a6e',
  stripe: '#635bff',
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
  const [datasetPath, setDatasetPath] = useState('pointclickcare data.txt')
  const [savingPath, setSavingPath] = useState(false)
  const [pasteContent, setPasteContent] = useState('')
  const [pasting, setPasting] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const data = await apiFetch('/accounts/stats')
      setStats(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    apiFetch('/config')
      .then((cfg) => {
        if (cfg && cfg.pro_dataset_path) {
          setDatasetPath(cfg.pro_dataset_path)
        }
      })
      .catch(() => {})
  }, [])

  const handleSavePath = async () => {
    setSavingPath(true)
    try {
      await apiFetch('/config', {
        method: 'PUT',
        body: JSON.stringify({
          data: {
            pro_dataset_path: datasetPath,
          },
        }),
      })
      message.success('Dataset path saved successfully')
    } catch (e: any) {
      message.error(e.message || 'Failed to save dataset path')
    } finally {
      setSavingPath(false)
    }
  }

  const handlePasteSubmit = async () => {
    if (!pasteContent.trim()) {
      message.warning('Please paste some data first')
      return
    }
    setPasting(true)
    try {
      const res = await apiFetch('/config/pro-dataset/paste', {
        method: 'POST',
        body: JSON.stringify({
          content: pasteContent,
        }),
      })
      if (res && res.filepath) {
        setDatasetPath(res.filepath)
        message.success('Pasted data saved and path configured successfully!')
      }
    } catch (e: any) {
      message.error(e.message || 'Failed to save pasted data')
    } finally {
      setPasting(false)
    }
  }

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
        <Button icon={<ReloadOutlined spin={loading} />} onClick={load} loading={loading}>
          Refresh
        </Button>
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

      <Card title="Dataset Configuration" style={{ marginTop: 16 }}>
        <Row gutter={[24, 24]}>
          <Col xs={24} md={12}>
            <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>Option 1: File Path</h3>
            <p style={{ color: '#7a8ba3', marginBottom: 12 }}>
              Specify the file path containing the registration profile data (pipe-delimited text file).
            </p>
            <div style={{ display: 'flex', gap: 12 }}>
              <Input 
                value={datasetPath} 
                onChange={(e) => setDatasetPath(e.target.value)} 
                placeholder="e.g. pointclickcare data.txt"
              />
              <Button type="primary" loading={savingPath} onClick={handleSavePath}>
                Save Path
              </Button>
            </div>
          </Col>
          <Col xs={24} md={12} style={{ borderLeft: '1px solid rgba(255,255,255,0.1)' }}>
            <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>Option 2: Direct Paste</h3>
            <p style={{ color: '#7a8ba3', marginBottom: 12 }}>
              Paste the pipe-delimited data directly. It will be saved and used for registrations.
            </p>
            <Input.TextArea
              rows={4}
              value={pasteContent}
              onChange={(e) => setPasteContent(e.target.value)}
              placeholder="Robert|Oliver|24647 Mohr|Hayward|CA|94545|04/06/1938|545-50-5372"
              style={{ marginBottom: 12 }}
            />
            <Button type="primary" loading={pasting} onClick={handlePasteSubmit}>
              Save Pasted Data
            </Button>
          </Col>
        </Row>
      </Card>

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

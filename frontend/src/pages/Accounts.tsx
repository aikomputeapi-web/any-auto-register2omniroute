import { useEffect, useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import {
  Table,
  Button,
  Input,
  InputNumber,
  Select,
  Tag,
  Space,
  Modal,
  Form,
  message,
  Popconfirm,
  Dropdown,
  Typography,
  Alert,
  DatePicker,
  theme,
} from 'antd';
import { useTranslation } from 'react-i18next';
import type { MenuProps } from 'antd';
import {
  ReloadOutlined,
  CopyOutlined,
  LinkOutlined,
  PlusOutlined,
  DownloadOutlined,
  UploadOutlined,
  DeleteOutlined,
  SyncOutlined,
} from '@ant-design/icons';
import { ChatGPTRegistrationModeSwitch } from '@/components/ChatGPTRegistrationModeSwitch'
import { TaskLogPanel } from '@/components/TaskLogPanel'
import { usePersistentChatGPTRegistrationMode } from '@/hooks/usePersistentChatGPTRegistrationMode'
import { parseBooleanConfigValue } from '@/lib/configValueParsers'
import { buildChatGPTRegistrationRequestAdapter } from '@/lib/chatgptRegistrationRequestAdapter'
import { apiFetch } from '@/lib/utils'
import { normalizeExecutorForPlatform } from '@/lib/platformExecutorOptions'

const { Text } = Typography

const STATUS_COLORS: Record<string, string> = {
  registered: 'default',
  trial: 'success',
  subscribed: 'success',
  expired: 'warning',
  invalid: 'error',
}

function parseExtraJson(raw: string | undefined) {
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function normalizeAccount(account: any) {
  const extra = parseExtraJson(account.extra_json)
  const syncStatuses = extra.sync_statuses && typeof extra.sync_statuses === 'object' ? extra.sync_statuses : {}
  const cpaSync = syncStatuses.cpa && typeof syncStatuses.cpa === 'object' ? syncStatuses.cpa : {}
  const sub2apiSync = syncStatuses.sub2api && typeof syncStatuses.sub2api === 'object' ? syncStatuses.sub2api : {}
  const omnirouteSync = syncStatuses.omniroute && typeof syncStatuses.omniroute === 'object' ? syncStatuses.omniroute : {}
  const cliproxySync = syncStatuses.cliproxyapi && typeof syncStatuses.cliproxyapi === 'object' ? syncStatuses.cliproxyapi : {}
  const chatgptLocal = extra.chatgpt_local && typeof extra.chatgpt_local === 'object' ? extra.chatgpt_local : {}
  return { ...account, extra, cpaSync, sub2apiSync, omnirouteSync, cliproxySync, chatgptLocal }
}

function formatSyncTime(value?: string) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function formatCreatedAt(value?: string) {
  if (!value) return { date: '-', time: '' }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return { date: value, time: '' }
  }
  return {
    date: date.toLocaleDateString(),
    time: date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
  }
}

function authStateMeta(state?: string) {
  switch (state) {
    case 'access_token_valid':
      return { color: 'success', label: 'Access token valid' }
    case 'account_deactivated':
      return { color: 'error', label: 'Deactivated' }
    case 'access_token_invalidated':
      return { color: 'error', label: 'Access token invalidated' }
    case 'unauthorized':
      return { color: 'error', label: 'Unauthorized' }
    case 'missing_access_token':
      return { color: 'default', label: 'Missing access token' }
    case 'banned_like':
      return { color: 'error', label: 'Possibly banned' }
    case 'probe_failed':
      return { color: 'warning', label: 'Probe failed' }
    default:
      return { color: 'default', label: 'Not probed' }
  }
}

function codexStateMeta(state?: string) {
  switch (state) {
    case 'usable':
      return { color: 'success', label: 'Usable' }
    case 'account_deactivated':
      return { color: 'error', label: 'Deactivated' }
    case 'access_token_invalidated':
      return { color: 'error', label: 'Access token invalidated' }
    case 'unauthorized':
      return { color: 'error', label: 'Unauthorized' }
    case 'payment_required':
      return { color: 'warning', label: 'Payment required / permission' }
    case 'quota_exhausted':
      return { color: 'warning', label: 'Quota exhausted' }
    case 'skipped_auth_invalid':
      return { color: 'default', label: 'Not checked' }
    case 'probe_failed':
      return { color: 'warning', label: 'Probe failed' }
    default:
      return { color: 'default', label: 'Not probed' }
  }
}

function planMeta(plan?: string) {
  switch ((plan || '').toLowerCase()) {
    case 'plus':
      return { color: 'success', label: 'Plus' }
    case 'team':
      return { color: 'processing', label: 'Team' }
    case 'enterprise':
      return { color: 'processing', label: 'Enterprise' }
    case 'pro':
      return { color: 'processing', label: 'Pro' }
    case 'free':
      return { color: 'default', label: 'Free' }
    default:
      return { color: 'default', label: 'Unknown' }
  }
}

function formatStructuredText(value?: string) {
  if (!value) return ''
  const trimmed = String(value).trim()
  if (!trimmed) return ''
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      return JSON.stringify(JSON.parse(trimmed), null, 2)
    } catch {
      return trimmed
    }
  }
  return trimmed
}

function SummaryField({
  label,
  value,
  code = false,
}: {
  label: string
  value?: string
  code?: boolean
}) {
  const { token } = theme.useToken()
  if (!value) return null

  const content = code ? formatStructuredText(value) : value
  const isBlock = code || content.length > 96 || content.includes('\n')

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '104px minmax(0, 1fr)',
        gap: 12,
        alignItems: 'start',
      }}
    >
      <Text type="secondary" style={{ fontSize: 12, lineHeight: '20px' }}>
        {label}
      </Text>
      {isBlock ? (
        <pre
          style={{
            margin: 0,
            padding: code ? '8px 10px' : 0,
            borderRadius: code ? token.borderRadius : 0,
            border: code ? `1px solid ${token.colorBorder}` : 'none',
            background: code ? token.colorBgElevated : 'transparent',
            color: code ? token.colorText : token.colorTextSecondary,
            fontFamily: code ? 'SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace' : 'inherit',
            fontSize: 12,
            lineHeight: 1.6,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            overflowWrap: 'anywhere',
            maxHeight: code ? 160 : 'none',
            overflow: code ? 'auto' : 'visible',
          }}
        >
          {content}
        </pre>
      ) : (
        <Text style={{ display: 'block', color: token.colorTextSecondary, lineHeight: '20px' }}>
          {content}
        </Text>
      )}
    </div>
  )
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  const { token } = theme.useToken()

  return (
    <div
      style={{
        marginTop: 16,
        padding: 14,
        borderRadius: token.borderRadiusLG,
        border: `1px solid ${token.colorBorder}`,
        background: token.colorFillAlter,
      }}
    >
      <div style={{ marginBottom: 10, fontWeight: 600, color: token.colorText }}>{title}</div>
      {children}
    </div>
  )
}

function LocalProbeSummary({ probe }: { probe: any }) {
  const { t } = useTranslation();
  const checkedAt = probe?.checked_at || probe?.auth?.checked_at || probe?.subscription?.checked_at || probe?.codex?.checked_at
  const auth = probe?.auth || {}
  const subscription = probe?.subscription || {}
  const codex = probe?.codex || {}

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        <Tag color={authStateMeta(auth.state).color}>Auth: {authStateMeta(auth.state).label}</Tag>
        <Tag color={planMeta(subscription.plan).color}>Subscription: {planMeta(subscription.plan).label}</Tag>
        <Tag color={codexStateMeta(codex.state).color}>Codex: {codexStateMeta(codex.state).label}</Tag>
      </div>
      <SummaryField label={t('probe_time')} value={checkedAt ? formatSyncTime(checkedAt) : ''} />
      <SummaryField label={t('auth_information')} value={auth.message} code />
      <SummaryField label={t('workspace_plan')} value={subscription.workspace_plan_type} />
      <SummaryField label={t('codex_information')} value={codex.message} code />
    </div>
  )
}

function cliproxyStateMeta(sync: any) {
  if (!sync || Object.keys(sync).length === 0) {
    return { color: 'default', label: 'Not synced' }
  }
  if (sync.remote_state === 'unreachable') {
    return { color: 'error', label: 'Unreachable' }
  }
  if (sync.remote_state === 'not_found') {
    return { color: 'default', label: 'Remote not found' }
  }
  if (!sync.uploaded) {
    return { color: 'default', label: 'Not found' }
  }
  if (sync.remote_state === 'usable') {
    return { color: 'success', label: 'Remote usable' }
  }
  if (sync.remote_state === 'account_deactivated') {
    return { color: 'error', label: 'Remote deactivated' }
  }
  if (sync.remote_state === 'access_token_invalidated') {
    return { color: 'error', label: 'Remote access token invalidated' }
  }
  if (sync.remote_state === 'unauthorized') {
    return { color: 'error', label: 'Remote unauthorized' }
  }
  if (sync.remote_state === 'payment_required') {
    return { color: 'warning', label: 'Remote payment required / permission' }
  }
  if (sync.remote_state === 'quota_exhausted') {
    return { color: 'warning', label: 'Remote quota exhausted' }
  }
  if (sync.status === 'active') {
    return { color: 'processing', label: 'Remote Active' }
  }
  if (sync.status === 'refreshing') {
    return { color: 'processing', label: 'Remote refreshing' }
  }
  if (sync.status === 'pending') {
    return { color: 'default', label: 'Remote pending' }
  }
  if (sync.status === 'error') {
    return { color: 'error', label: 'Remote error' }
  }
  if (sync.status === 'disabled') {
    return { color: 'default', label: 'Remote disabled' }
  }
  return { color: 'default', label: 'Not synced' }
}

function uploadSyncMeta(sync: any) {
  if (!sync || Object.keys(sync).length === 0) {
    return { color: 'default', label: 'Not uploaded' }
  }
  if (sync.uploaded || sync.uploaded_at) {
    return { color: 'success', label: 'Uploaded' }
  }
  if (sync.last_attempt_ok === false) {
    return { color: 'error', label: 'Failed' }
  }
  if (sync.last_attempt_ok === true || sync.last_attempt_at) {
    return { color: 'processing', label: 'Attempted' }
  }
  return { color: 'default', label: 'Not uploaded' }
}

function uploadSyncTitle(name: string, sync: any) {
  if (!sync || Object.keys(sync).length === 0) {
    return `${name} not uploaded`
  }

  const parts: string[] = []
  if (sync.uploaded_at) {
    parts.push(`Success time: ${formatSyncTime(sync.uploaded_at)}`)
  }
  if (sync.last_attempt_at) {
    parts.push(`Last attempt: ${formatSyncTime(sync.last_attempt_at)}`)
  }
  if (sync.last_message) {
    parts.push(`Result: ${sync.last_message}`)
  }
  return parts.join('\n') || `${name} status recorded`
}

function CliproxySyncSummary({ sync }: { sync: any }) {
  const meta = cliproxyStateMeta(sync)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        <Tag color={meta.color}>{meta.label}</Tag>
        {sync?.status ? <Tag>{`status: ${sync.status}`}</Tag> : null}
      </div>
      <SummaryField label="Status information" value={sync?.status_message} code />
      <SummaryField label="auth-file" value={sync?.name} />
      <SummaryField label="API URL" value={sync?.base_url} />
      <SummaryField label="Sync time" value={sync?.last_synced_at ? formatSyncTime(sync.last_synced_at) : ''} />
      <SummaryField label="Remote refresh time" value={sync?.last_refresh ? formatSyncTime(sync.last_refresh) : ''} />
      <SummaryField label="Next retry time" value={sync?.next_retry_after ? formatSyncTime(sync.next_retry_after) : ''} />
      <SummaryField label="Probe information" value={sync?.last_probe_message} code />
    </div>
  )
}

function ActionButtons({ acc, onRefresh, actions, onDelete }: { acc: any; onRefresh: () => void; actions: any[]; onDelete: (id: number) => void }) {
  const { token } = theme.useToken()
  const [resultOpen, setResultOpen] = useState(false)
  const [resultTitle, setResultTitle] = useState('')
  const [resultStatus, setResultStatus] = useState<'success' | 'error'>('success')
  const [resultText, setResultText] = useState('')
  const [resultUrl, setResultUrl] = useState('')
  const [resultProbe, setResultProbe] = useState<any>(null)
  const [resultCliproxySync, setResultCliproxySync] = useState<any>(null)
  const [runningActionId, setRunningActionId] = useState<string | null>(null)

  const showResult = (title: string, status: 'success' | 'error', text: string, url = '', probe: any = null, cliproxySync: any = null) => {
    setResultTitle(title)
    setResultStatus(status)
    setResultText(text)
    setResultUrl(url)
    setResultProbe(probe)
    setResultCliproxySync(cliproxySync)
    setResultOpen(true)
  }

  const copyResultUrl = async () => {
    if (!resultUrl) return
    try {
      await navigator.clipboard.writeText(resultUrl)
      message.success('Link copied')
    } catch {
      message.error('Copy failed')
    }
  }

  const handleAction = async (actionId: string) => {
    if (runningActionId) return
    const actionLabel = actions.find((item) => item.id === actionId)?.label || actionId
    const toastKey = `account-action:${acc?.id}:${actionId}`
    setRunningActionId(actionId)
    message.loading({ content: `${actionLabel} running...`, key: toastKey, duration: 0 })

    try {
      const r = await apiFetch(`/actions/${acc.platform}/${acc.id}/${actionId}`, {
        method: 'POST',
        body: JSON.stringify({ params: {} }),
      })
      if (!r.ok) {
        const data = r.data || {}
        const probe = typeof data === 'object' && data ? data.probe || null : null
        const cliproxySync = typeof data === 'object' && data ? data.sync || null : null
        message.error({ content: `${actionLabel} failed`, key: toastKey })
        showResult(actionLabel, 'error', r.error || data.message || 'Action failed', '', probe, cliproxySync)
        onRefresh()
        return
      }
      const data = r.data || {}
      if (data.url || data.checkout_url || data.cashier_url) {
        const targetUrl = data.url || data.checkout_url || data.cashier_url
        message.success({ content: `${actionLabel} completed`, key: toastKey })
        showResult(actionLabel, 'success', 'Operation successful, please open or copy the link in the dialog.', targetUrl)
      } else {
        message.success({ content: data.message || `${actionLabel} completed`, key: toastKey })
        const probe = typeof data === 'object' && data ? data.probe || null : null
        const cliproxySync = typeof data === 'object' && data ? data.sync || null : null
        const text =
          probe
            ? String(data.message || 'Operation successful')
            : cliproxySync
            ? String(data.message || 'Operation successful')
            : typeof data === 'string'
            ? data
            : Object.keys(data).length > 0
              ? JSON.stringify(data, null, 2)
              : 'Operation successful'
        showResult(actionLabel, 'success', text, '', probe, cliproxySync)
      }
      onRefresh()
    } catch (e: any) {
      const detail = e?.message ? String(e.message) : 'Request failed'
      message.error({ content: detail, key: toastKey })
      showResult(actionLabel, 'error', detail)
    } finally {
      setRunningActionId(null)
    }
  }

  const btnStyle: React.CSSProperties = {
    fontSize: 11,
    minHeight: 34,
    height: 'auto',
    padding: '4px 8px',
    lineHeight: '1.2',
    borderRadius: 6,
    width: '100%',
    textAlign: 'center',
    whiteSpace: 'normal',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxShadow: 'none',
    transition: 'all 0.2s',
  }

  // All buttons: platform actions + Details + Delete
  const allButtons = [
    ...actions.map((a) => ({
      id: a.id,
      label: a.label,
      fullLabel: a.label,
      isDelete: false,
      isPlatformAction: true,
    })),
    { id: '__details__', label: 'Details', fullLabel: 'Details', isDelete: false, isPlatformAction: false },
    { id: '__delete__', label: 'Delete', fullLabel: 'Delete', isDelete: true, isPlatformAction: false },
  ]

  return (
    <>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, 1fr)',
          gap: 6,
          width: '100%',
        }}
      >
        {allButtons.map((btn) => {
          if (btn.id === '__delete__') {
            return (
              <Popconfirm
                key="__delete__"
                title="Delete this account?"
                onConfirm={() => onDelete(acc.id)}
                okText="Delete"
                cancelText="Cancel"
                okButtonProps={{ danger: true }}
              >
                <Button
                  danger
                  style={btnStyle}
                  title="Delete"
                >
                  Delete
                </Button>
              </Popconfirm>
            )
          }
          if (btn.id === '__details__') {
            return (
              <Button
                key="__details__"
                type="default"
                style={{ ...btnStyle, borderColor: token.colorPrimary, color: token.colorPrimary }}
                title="Details"
                onClick={() => {
                  // Trigger detail modal via event — handled by parent via onRow or separate callback
                  // We'll propagate via a custom event
                  const evt = new CustomEvent('open-account-detail', { detail: { id: acc.id }, bubbles: true })
                  document.dispatchEvent(evt)
                }}
              >
                Details
              </Button>
            )
          }
          return (
            <Button
              key={btn.id}
              style={btnStyle}
              loading={runningActionId === btn.id}
              disabled={Boolean(runningActionId) && runningActionId !== btn.id}
              title={btn.fullLabel}
              onClick={() => handleAction(btn.id)}
            >
              {btn.label}
            </Button>
          )
        })}
      </div>
      <Modal
        title={resultTitle}
        open={resultOpen}
        onCancel={() => setResultOpen(false)}
        footer={[
          resultUrl ? (
            <Button key="copy" onClick={copyResultUrl}>
              Copy link
            </Button>
          ) : null,
          resultUrl ? (
            <Button
              key="open"
              type="primary"
              onClick={() => window.open(resultUrl, '_blank', 'noopener,noreferrer')}
            >
              Open link
            </Button>
          ) : null,
          <Button key="ok" type={resultUrl ? 'default' : 'primary'} onClick={() => setResultOpen(false)}>
            OK
          </Button>,
        ].filter(Boolean)}
        maskClosable={false}
      >
        <Alert
          type={resultStatus}
          showIcon
          message={resultStatus === 'success' ? 'Action completed' : 'Action failed'}
          style={{ marginBottom: 12 }}
        />
        {resultProbe ? (
          <div style={{ marginBottom: 12 }}>
            <LocalProbeSummary probe={resultProbe} />
          </div>
        ) : null}
        {resultCliproxySync ? (
          <div style={{ marginBottom: 12 }}>
            <CliproxySyncSummary sync={resultCliproxySync} />
          </div>
        ) : null}
        {resultUrl ? (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Text copyable={{ text: resultUrl }} style={{ wordBreak: 'break-all' }}>
              {resultUrl}
            </Text>
          </Space>
        ) : null}
        {resultText ? (
          <pre
            style={{
              margin: 0,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              fontFamily: 'monospace',
              fontSize: 12,
            }}
          >
            {resultText}
          </pre>
        ) : null}
      </Modal>
    </>
  )
}

export default function Accounts() {
  const { platform } = useParams<{ platform: string }>()
  const { token } = theme.useToken()
  const [currentPlatform, setCurrentPlatform] = useState(platform || 'chatgpt')
  const [accounts, setAccounts] = useState<any[]>([])
  const [platformActions, setPlatformActions] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [createdAtStart, setCreatedAtStart] = useState('')
  const [createdAtEnd, setCreatedAtEnd] = useState('')
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  const [registerModalOpen, setRegisterModalOpen] = useState(false)
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [importModalOpen, setImportModalOpen] = useState(false)
  const [detailModalOpen, setDetailModalOpen] = useState(false)
  const [currentAccount, setCurrentAccount] = useState<any>(null)

  const [registerForm] = Form.useForm()
  const [addForm] = Form.useForm()
  const [detailForm] = Form.useForm()
  const { mode: chatgptRegistrationMode, setMode: setChatgptRegistrationMode } =
    usePersistentChatGPTRegistrationMode()
  const [importText, setImportText] = useState('')
  const [importLoading, setImportLoading] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [registerLoading, setRegisterLoading] = useState(false)
  const [cpaSyncLoading, setCpaSyncLoading] = useState<'pending' | 'selected' | ''>('')
  const [cpaUploadLoading, setCpaUploadLoading] = useState<'all' | 'selected' | ''>('')
  const [statusSyncLoading, setStatusSyncLoading] = useState<'probe_selected' | 'probe_all' | 'remote_selected' | 'remote_all' | ''>('')
  const [batchActionLoading, setBatchActionLoading] = useState<string | null>(null)

  useEffect(() => {
    if (platform) setCurrentPlatform(platform)
  }, [platform])

  useEffect(() => {
    if (!detailModalOpen || !currentAccount) return
    detailForm.setFieldsValue({
      status: currentAccount.status,
      token: currentAccount.token,
    })
  }, [detailModalOpen, currentAccount, detailForm])

  const load = useCallback(async () => {
    if (createdAtStart && createdAtEnd && new Date(createdAtStart).getTime() > new Date(createdAtEnd).getTime()) {
      message.warning('Start time cannot be later than end time')
      setAccounts([])
      setTotal(0)
      return
    }

    setLoading(true)
    try {
      const params = new URLSearchParams({ platform: currentPlatform, page: String(page), page_size: String(pageSize) })
      if (search) params.set('email', search)
      if (filterStatus) params.set('status', filterStatus)
      if (createdAtStart) params.set('created_at_start', createdAtStart)
      if (createdAtEnd) params.set('created_at_end', createdAtEnd)
      const data = await apiFetch(`/accounts?${params}`)
      setAccounts((data.items || []).map(normalizeAccount))
      setTotal(data.total)
    } finally {
      setLoading(false)
    }
  }, [currentPlatform, search, filterStatus, createdAtStart, createdAtEnd, page, pageSize])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    apiFetch(`/actions/${currentPlatform}`)
      .then((data) => setPlatformActions(data.actions || []))
      .catch(() => setPlatformActions([]))
  }, [currentPlatform])

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (!detail?.id) return
      const found = accounts.find((a: any) => a.id === detail.id)
      if (found) {
        setCurrentAccount(found)
        setDetailModalOpen(true)
      }
    }
    document.addEventListener('open-account-detail', handler)
    return () => document.removeEventListener('open-account-detail', handler)
  }, [accounts])

  const copyText = (text: string) => {
    navigator.clipboard.writeText(text)
    message.success('Copied')
  }

  const getRefreshToken = (record: any): string => {
    try {
      const extra = JSON.parse(record.extra_json || '{}')
      return extra.refresh_token || extra.refreshToken || ''
    } catch {
      return ''
    }
  }

  const exportCsv = () => {
    const quoteCsv = (value: any) => {
      const text = value == null ? '' : String(value)
      return `"${text.replace(/"/g, '""')}"`
    }

    const downloadCsv = (content: string) => {
      const blob = new Blob([`\uFEFF${content}`], { type: 'text/csv;charset=utf-8;' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${currentPlatform}_accounts.csv`
      a.click()
      URL.revokeObjectURL(url)
    }

    if (currentPlatform === 'kiro' || currentPlatform === 'kiro2') {
      const header = ['Email', 'Nickname', 'Login method', 'RefreshToken', 'ClientId', 'ClientSecret', 'Region']
      const rows = accounts.map((a) => {
        const nickname = a.extra?.name || String(a.email || '').split('@')[0] || ''
        const provider = a.extra?.provider || 'BuilderId'
        const refreshToken = a.extra?.refreshToken || ''
        const clientId = a.extra?.clientId || ''
        const clientSecret = a.extra?.clientSecret || ''
        const region = a.extra?.region || 'us-east-1'

        return [
          a.email || '',
          nickname,
          provider,
          refreshToken,
          clientId,
          clientSecret,
          region,
        ].map(quoteCsv).join(',')
      })

      downloadCsv([header.map(quoteCsv).join(','), ...rows].join('\r\n'))
      return
    }

    const header = ['email', 'password', 'status', 'region', 'cashier_url', 'created_at']
    if (currentPlatform === 'kiro' || currentPlatform === 'kiro2') {
      header.push('accessToken', 'refreshToken', 'clientId', 'clientSecret')
    } else if (currentPlatform === 'chatgpt') {
      header.push('token', 'refresh_token')
    } else {
      header.push('token')
    }

    const rows = accounts.map((a) => {
      const baseRow = [a.email, a.password, a.status, a.region, a.cashier_url, a.created_at].map(quoteCsv)
      if (currentPlatform === 'kiro' || currentPlatform === 'kiro2') {
        baseRow.push(quoteCsv(a.extra?.accessToken || a.extra?.webAccessToken || a.token))
        baseRow.push(quoteCsv(a.extra?.refreshToken))
        baseRow.push(quoteCsv(a.extra?.clientId))
        baseRow.push(quoteCsv(a.extra?.clientSecret))
      } else if (currentPlatform === 'chatgpt') {
        baseRow.push(quoteCsv(a.token))
        baseRow.push(quoteCsv(getRefreshToken(a)))
      } else {
        baseRow.push(quoteCsv(a.token))
      }
      return baseRow.join(',')
    })

    downloadCsv([header.map(quoteCsv).join(','), ...rows].join('\r\n'))
  }

  const handleDelete = async (id: number) => {
    await apiFetch(`/accounts/${id}`, { method: 'DELETE' })
    message.success('Delete successful')
    load()
  }

  const handleBatchDelete = async () => {
    if (selectedRowKeys.length === 0) return
    await apiFetch('/accounts/batch-delete', {
      method: 'POST',
      body: JSON.stringify({ ids: Array.from(selectedRowKeys) }),
    })
    message.success('Batch delete successful')
    setSelectedRowKeys([])
    load()
  }

  const handleAdd = async () => {
    const values = await addForm.validateFields()
    await apiFetch('/accounts', {
      method: 'POST',
      body: JSON.stringify({ ...values, platform: currentPlatform }),
    })
    message.success('Add successful')
    setAddModalOpen(false)
    addForm.resetFields()
    load()
  }

  const handleImport = async () => {
    if (!importText.trim()) return
    setImportLoading(true)
    try {
      const lines = importText.trim().split('\n').filter(Boolean)
      const res = await apiFetch('/accounts/import', {
        method: 'POST',
        body: JSON.stringify({ platform: currentPlatform, lines }),
      })
      message.success(`Import successful ${res.created}  items`)
      setImportModalOpen(false)
      setImportText('')
      load()
    } catch (e: any) {
      message.error(`ImportFailed: ${e.message}`)
    } finally {
      setImportLoading(false)
    }
  }

  const handleRegister = async () => {
    const values = await registerForm.validateFields()
    setRegisterLoading(true)
    try {
      const cfg = await apiFetch('/config')
      const executorType = normalizeExecutorForPlatform(currentPlatform, cfg.default_executor)
      const registerExtra = {
        mail_provider: cfg.mail_provider || 'luckmail',
        applemail_base_url: cfg.applemail_base_url,
        applemail_pool_dir: cfg.applemail_pool_dir,
        applemail_pool_file: cfg.applemail_pool_file,
        applemail_mailboxes: cfg.applemail_mailboxes,
        laoudo_auth: cfg.laoudo_auth,
        laoudo_email: cfg.laoudo_email,
        laoudo_account_id: cfg.laoudo_account_id,
        gptmail_base_url: cfg.gptmail_base_url,
        gptmail_api_key: cfg.gptmail_api_key,
        gptmail_domain: cfg.gptmail_domain,
        maliapi_base_url: cfg.maliapi_base_url,
        maliapi_api_key: cfg.maliapi_api_key,
        maliapi_domain: cfg.maliapi_domain,
        maliapi_auto_domain_strategy: cfg.maliapi_auto_domain_strategy,
        yescaptcha_key: cfg.yescaptcha_key,
        moemail_api_url: cfg.moemail_api_url,
        moemail_api_key: cfg.moemail_api_key,
        skymail_api_base: cfg.skymail_api_base,
        skymail_token: cfg.skymail_token,
        skymail_domain: cfg.skymail_domain,
        cloudmail_api_base: cfg.cloudmail_api_base,
        cloudmail_admin_email: cfg.cloudmail_admin_email,
        cloudmail_admin_password: cfg.cloudmail_admin_password,
        cloudmail_domain: cfg.cloudmail_domain,
        cloudmail_subdomain: cfg.cloudmail_subdomain,
        cloudmail_timeout: cfg.cloudmail_timeout,
        duckmail_address: cfg.duckmail_address,
        duckmail_password: cfg.duckmail_password,
        duckmail_api_url: cfg.duckmail_api_url,
        duckmail_provider_url: cfg.duckmail_provider_url,
        duckmail_bearer: cfg.duckmail_bearer,
        freemail_api_url: cfg.freemail_api_url,
        freemail_admin_token: cfg.freemail_admin_token,
        freemail_username: cfg.freemail_username,
        freemail_password: cfg.freemail_password,
        freemail_domain: cfg.freemail_domain,
        cfworker_api_url: cfg.cfworker_api_url,
        cfworker_admin_token: cfg.cfworker_admin_token,
        cfworker_custom_auth: cfg.cfworker_custom_auth,
        cfworker_domain: cfg.cfworker_domain,
        cfworker_subdomain: cfg.cfworker_subdomain,
        cfworker_random_subdomain: parseBooleanConfigValue(cfg.cfworker_random_subdomain),
        cfworker_random_name_subdomain: parseBooleanConfigValue(cfg.cfworker_random_name_subdomain),
        cfworker_fingerprint: cfg.cfworker_fingerprint,
        smstome_cookie: cfg.smstome_cookie,
        smstome_country_slugs: cfg.smstome_country_slugs,
        smstome_phone_attempts: cfg.smstome_phone_attempts,
        smstome_otp_timeout_seconds: cfg.smstome_otp_timeout_seconds,
        smstome_poll_interval_seconds: cfg.smstome_poll_interval_seconds,
        smstome_sync_max_pages_per_country: cfg.smstome_sync_max_pages_per_country,
        luckmail_base_url: cfg.luckmail_base_url,
        luckmail_api_key: cfg.luckmail_api_key,
        luckmail_email_type: cfg.luckmail_email_type,
        luckmail_domain: cfg.luckmail_domain,
      }
      const chatgptRegistrationRequestAdapter =
        buildChatGPTRegistrationRequestAdapter(
          currentPlatform,
          chatgptRegistrationMode,
        )
      const adaptedRegisterExtra = chatgptRegistrationRequestAdapter
        ? chatgptRegistrationRequestAdapter.extendExtra(registerExtra)
        : registerExtra

      const res = await apiFetch('/tasks/register', {
        method: 'POST',
        body: JSON.stringify({
          platform: currentPlatform,
          count: values.count,
          concurrency: values.concurrency,
          register_delay_seconds: values.register_delay_seconds || 0,
          executor_type: executorType,
          captcha_solver: cfg.default_captcha_solver || 'yescaptcha',
          proxy: null,
          extra: adaptedRegisterExtra,
        }),
      })
      setTaskId(res.task_id)
    } finally {
      setRegisterLoading(false)
    }
  }

  const handleDetailSave = async () => {
    const values = await detailForm.validateFields()
    await apiFetch(`/accounts/${currentAccount.id}`, {
      method: 'PATCH',
      body: JSON.stringify(values),
    })
    message.success('Save successful')
    setDetailModalOpen(false)
    load()
  }

  const showCpaSyncResult = (title: string, result: any) => {
    const lines = (result.items || [])
      .flatMap((item: any) =>
        (item.results || []).map((syncResult: any) => ({
          email: item.email,
          platform: item.platform,
          ok: Boolean(syncResult.ok),
          name: syncResult.name || 'CPA',
          msg: syncResult.msg || '',
        })),
      )
      .filter((item: any) => !item.ok)
      .map((item: any) => `[${item.platform}] ${item.email || '-'} / ${item.name}: ${item.msg || 'Failed'}`)

    if (lines.length === 0) return

    Modal.info({
      title,
      width: 760,
      content: (
        <pre
          style={{
            margin: 0,
            maxHeight: 360,
            overflow: 'auto',
            padding: 12,
            borderRadius: 8,
            background: 'rgba(127,127,127,0.08)',
            fontSize: 12,
            lineHeight: 1.5,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {lines.join('\n')}
        </pre>
      ),
    })
  }

  const showBatchActionResult = (title: string, result: any) => {
    const lines = (result.items || [])
      .filter((item: any) => !item.ok)
      .map((item: any) => `[${item.id || '-'}] ${item.email || '-'}: ${item.message || 'Failed'}`)

    if (lines.length === 0) return

    Modal.info({
      title,
      width: 760,
      content: (
        <pre
          style={{
            margin: 0,
            maxHeight: 360,
            overflow: 'auto',
            padding: 12,
            borderRadius: 8,
            background: 'rgba(127,127,127,0.08)',
            fontSize: 12,
            lineHeight: 1.5,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {lines.join('\n')}
        </pre>
      ),
    })
  }

  const handleCpaBackfill = async (mode: 'pending' | 'selected') => {
    if (currentPlatform !== 'chatgpt') return

    const body: Record<string, unknown> = {
      platforms: ['chatgpt'],
    }

    if (mode === 'selected') {
      const accountIds = Array.from(selectedRowKeys)
        .map((value) => Number(value))
        .filter((value) => Number.isInteger(value) && value > 0)

      if (accountIds.length === 0) {
        message.warning('Please select the accounts to upload first')
        return
      }
      body.account_ids = accountIds
    } else {
      body.pending_only = true
      if (filterStatus) body.status = filterStatus
      if (search) body.email = search
    }

    setCpaSyncLoading(mode)
    try {
      const result = await apiFetch('/integrations/backfill', {
        method: 'POST',
        body: JSON.stringify(body),
      })

      const actionLabel = mode === 'selected' ? 'Selected accounts backfill' : 'Remote-not-found backfill'
      if (!result.total) {
        message.info('No accounts to process')
      } else if (!result.failed && !result.skipped) {
        message.success(`${actionLabel} completed: success ${result.success} / ${result.total}`)
      } else if (!result.failed) {
        message.success(`${actionLabel} completed: success ${result.success}, skipped ${result.skipped} / ${result.total}`)
      } else if (!result.success) {
        message.error(`${actionLabel} failed: success ${result.success}, skipped ${result.skipped} / ${result.total}`)
      } else {
        message.warning(`${actionLabel} partially completed: success ${result.success}, skipped ${result.skipped} / ${result.total}`)
      }

      showCpaSyncResult(`${actionLabel} result`, result)
      await load()
    } catch (e: any) {
      message.error(`CPA upload failed: ${e.message}`)
    } finally {
      setCpaSyncLoading('')
    }
  }

  const handleBatchStatusSync = async (kind: 'probe' | 'remote', scope: 'selected' | 'all') => {
    if (currentPlatform !== 'chatgpt') return

    const loadingKey = `${kind}_${scope}` as typeof statusSyncLoading
    const actionId = kind === 'probe' ? 'probe_local_status' : 'sync_cliproxyapi_status'
    const actionLabel = kind === 'probe' ? 'Local status sync' : 'CLIProxyAPI status sync'
    const scopeLabel = scope === 'selected' ? 'Selected accounts' : 'Currently filtered accounts'
    const toastKey = `status-sync:${loadingKey}`

    const body: Record<string, unknown> = {
      params: {},
    }

    if (scope === 'selected') {
      const accountIds = Array.from(selectedRowKeys)
        .map((value) => Number(value))
        .filter((value) => Number.isInteger(value) && value > 0)

      if (accountIds.length === 0) {
        message.warning('Please select the accounts to sync first')
        return
      }
      body.account_ids = accountIds
    } else {
      body.all_filtered = true
      if (search) body.email = search
      if (filterStatus) body.status = filterStatus
    }

    setStatusSyncLoading(loadingKey)
    message.loading({ content: `${scopeLabel} ${actionLabel} in progress...`, key: toastKey, duration: 0 })
    try {
      const result = await apiFetch(`/actions/${currentPlatform}/${actionId}/batch`, {
        method: 'POST',
        body: JSON.stringify(body),
      })

      if (!result.total) {
        message.info({ content: 'No accounts to process', key: toastKey })
      } else if (!result.failed) {
        message.success({ content: `${scopeLabel} ${actionLabel} completed: success ${result.success} / ${result.total}`, key: toastKey })
      } else if (!result.success) {
        message.error({ content: `${scopeLabel} ${actionLabel} failed: success ${result.success} / ${result.total}`, key: toastKey })
      } else {
        message.warning({ content: `${scopeLabel} ${actionLabel} partially completed: success ${result.success} / ${result.total}`, key: toastKey })
      }

      showBatchActionResult(`${scopeLabel} ${actionLabel} result`, result)
      await load()
    } catch (e: any) {
      message.error({ content: `${actionLabel}Failed: ${e.message}`, key: toastKey })
    } finally {
      setStatusSyncLoading('')
    }
  }

  const handleBatchUploadCpa = async (scope: 'selected' | 'all') => {
    const toastKey = `batch-upload-cpa:${scope}`
    const scopeLabel = scope === 'selected' ? 'Selected accounts' : 'Currently filtered accounts'

    const body: Record<string, unknown> = {
      params: {},
    }

    if (scope === 'selected') {
      const accountIds = Array.from(selectedRowKeys)
        .map((value) => Number(value))
        .filter((value) => Number.isInteger(value) && value > 0)

      if (accountIds.length === 0) {
        message.warning('Please select the accounts to import into CPA first')
        return
      }
      body.account_ids = accountIds
    } else {
      body.all_filtered = true
      if (search) body.email = search
      if (filterStatus) body.status = filterStatus
    }

    setCpaUploadLoading(scope)
    message.loading({ content: `${scopeLabel} importing into CPA...`, key: toastKey, duration: 0 })
    try {
      const result = await apiFetch(`/actions/${currentPlatform}/upload_cpa/batch`, {
        method: 'POST',
        body: JSON.stringify(body),
      })

      if (!result.total) {
        message.info({ content: 'No accounts to process', key: toastKey })
      } else if (!result.failed) {
        message.success({ content: `${scopeLabel} import into CPA completed: success ${result.success} / ${result.total}`, key: toastKey })
      } else if (!result.success) {
        message.error({ content: `${scopeLabel} import into CPA failed: success ${result.success} / ${result.total}`, key: toastKey })
      } else {
        message.warning({ content: `${scopeLabel} import into CPA partially completed: success ${result.success} / ${result.total}`, key: toastKey })
      }

      showBatchActionResult(`${scopeLabel} import into CPA result`, result)
      await load()
    } catch (e: any) {
      message.error({ content: `Import CPA Failed: ${e.message}`, key: toastKey })
    } finally {
      setCpaUploadLoading('')
    }
  }

  const handleBatchAction = async (actionId: string, actionLabel: string) => {
    const scope = selectedRowKeys.length > 0 ? 'selected' : 'all'
    const scopeLabel = scope === 'selected' ? 'Selected accounts' : 'Currently filtered accounts'
    const toastKey = `batch-action:${actionId}:${scope}`

    const body: Record<string, unknown> = {
      params: {},
    }

    if (scope === 'selected') {
      const accountIds = Array.from(selectedRowKeys)
        .map((value) => Number(value))
        .filter((value) => Number.isInteger(value) && value > 0)
      body.account_ids = accountIds
    } else {
      body.all_filtered = true
      if (search) body.email = search
      if (filterStatus) body.status = filterStatus
    }

    setBatchActionLoading(actionId)
    message.loading({ content: `${scopeLabel} ${actionLabel} in progress...`, key: toastKey, duration: 0 })
    try {
      const result = await apiFetch(`/actions/${currentPlatform}/${actionId}/batch`, {
        method: 'POST',
        body: JSON.stringify(body),
      })

      if (!result.total) {
        message.info({ content: 'No accounts to process', key: toastKey })
      } else if (!result.failed) {
        message.success({ content: `${scopeLabel} ${actionLabel} completed: success ${result.success} / ${result.total}`, key: toastKey })
      } else if (!result.success) {
        message.error({ content: `${scopeLabel} ${actionLabel} failed: success ${result.success} / ${result.total}`, key: toastKey })
      } else {
        message.warning({ content: `${scopeLabel} ${actionLabel} partially completed: success ${result.success} / ${result.total}`, key: toastKey })
      }

      showBatchActionResult(`${scopeLabel} ${actionLabel} result`, result)
      await load()
    } catch (e: any) {
      message.error({ content: `${actionLabel} Failed: ${e.message}`, key: toastKey })
    } finally {
      setBatchActionLoading(null)
    }
  }

  const getStatusSyncScope = (): 'selected' | 'all' => (selectedRowKeys.length > 0 ? 'selected' : 'all')

  const getBackfillScope = (): 'selected' | 'pending' => (selectedRowKeys.length > 0 ? 'selected' : 'pending')

  const getUploadCpaScope = (): 'selected' | 'all' => (selectedRowKeys.length > 0 ? 'selected' : 'all')

  const backfillButtonLabel = () => {
    const scope = getBackfillScope()
    const count = scope === 'selected' ? selectedRowKeys.length : total
    return scope === 'selected' ? `Backfill selected Remote not found (${count})` : `Backfill Remote not found (${count})`
  }

  const uploadCpaButtonLabel = () => {
    const scope = getUploadCpaScope()
    const count = scope === 'selected' ? selectedRowKeys.length : total
    return scope === 'selected' ? `Import selected CPA (${count})` : `Import filtered CPA (${count})`
  }

  const isChatgptPlatform = currentPlatform === 'chatgpt'
  const hasUploadCpaAction = platformActions.some((item) => item?.id === 'upload_cpa')
  const monospaceStyle: React.CSSProperties = {
    fontFamily: 'SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace',
    fontSize: 12,
  }
  const cellStackStyle: React.CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    minWidth: 0,
  }
  const secretPreviewStyle: React.CSSProperties = {
    ...monospaceStyle,
    filter: 'blur(4px)',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    maxWidth: '100%',
    opacity: 0.9,
  }
  const compactPanelStyle: React.CSSProperties = {
    padding: '8px 10px',
    borderRadius: token.borderRadiusLG,
    border: `1px solid ${token.colorBorder}`,
    background: token.colorFillAlter,
  }

  const columns: any[] = [
    {
      title: 'Account',
      key: 'account_card',
      render: (_: any, record: any) => {
        const rt = getRefreshToken(record)
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, minWidth: 0 }}>
            {/* Action buttons grid — left side */}
            <div style={{ flexShrink: 0, width: 300 }}>
              <ActionButtons
                acc={record}
                onRefresh={load}
                actions={platformActions}
                onDelete={handleDelete}
              />
            </div>
            {/* Identity info — right side, stacked */}
            <div style={{ ...cellStackStyle, flex: 1, minWidth: 0 }}>
              {/* Email row */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, minWidth: 0 }}>
                <Text
                  style={{ ...monospaceStyle, flex: 1, minWidth: 0 }}
                  ellipsis={{ tooltip: record.email }}
                >
                  {record.email}
                </Text>
                <Button type="text" size="small" icon={<CopyOutlined />} style={{ flexShrink: 0 }} onClick={() => copyText(record.email)} />
              </div>
              {/* Password row */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, minWidth: 0 }}>
                <Text style={{ ...secretPreviewStyle, flex: 1, minWidth: 0 }} title={record.password}>
                  {record.password}
                </Text>
                <Button type="text" size="small" icon={<CopyOutlined />} style={{ flexShrink: 0 }} onClick={() => copyText(record.password)} />
              </div>
              {/* Refresh token row (if present) */}
              {rt ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 4, minWidth: 0 }}>
                  <Text style={{ ...secretPreviewStyle, fontSize: 11, flex: 1, minWidth: 0 }} title={rt}>
                    {rt}
                  </Text>
                  <Button type="text" size="small" icon={<CopyOutlined />} style={{ flexShrink: 0 }} onClick={() => copyText(rt)} />
                </div>
              ) : null}
              {/* Status + date row */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                <Tag color={STATUS_COLORS[record.status] || 'default'} style={{ margin: 0, fontSize: 11 }}>{record.status}</Tag>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {formatCreatedAt(record.created_at).date}
                </Text>
                {record.user_id ? (
                  <Text type="secondary" style={{ fontSize: 11 }} ellipsis={{ tooltip: record.user_id }}>
                    UID: {record.user_id}
                  </Text>
                ) : null}
              </div>
            </div>
          </div>
        )
      },
    },
  ]

  if (isChatgptPlatform) {
    columns.push({
      title: 'Status',
      key: 'chatgpt_status',
      width: 240,
      render: (_: any, record: any) => {
        const auth = record.chatgptLocal?.auth || {}
        const subscription = record.chatgptLocal?.subscription || {}
        const codex = record.chatgptLocal?.codex || {}
        const cpaSync = record.cpaSync || {}
        const sub2apiSync = record.sub2apiSync || {}
        const omnirouteSync = record.omnirouteSync || {}
        const cliproxySync = record.cliproxySync || {}
        const authMeta = authStateMeta(auth.state)
        const planTag = planMeta(subscription.plan)
        const codexMeta = codexStateMeta(codex.state)
        const cpaMeta = uploadSyncMeta(cpaSync)
        const sub2apiMeta = uploadSyncMeta(sub2apiSync)
        const omnirouteMeta = uploadSyncMeta(omnirouteSync)
        const cliproxyMeta = cliproxyStateMeta(cliproxySync)
        return (
          <div style={{ ...cellStackStyle, ...compactPanelStyle }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              <Tag color={authMeta.color} style={{ fontSize: 11, margin: 0 }}>{authMeta.label}</Tag>
              <Tag color={planTag.color} style={{ fontSize: 11, margin: 0 }}>{planTag.label}</Tag>
              <Tag color={codexMeta.color} style={{ fontSize: 11, margin: 0 }}>Codex: {codexMeta.label}</Tag>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              <Tag color={cpaMeta.color} title={uploadSyncTitle('CPA', cpaSync)} style={{ fontSize: 11, margin: 0 }}>CPA: {cpaMeta.label}</Tag>
              <Tag color={sub2apiMeta.color} title={uploadSyncTitle('Sub2API', sub2apiSync)} style={{ fontSize: 11, margin: 0 }}>S2A: {sub2apiMeta.label}</Tag>
              <Tag color={omnirouteMeta.color} title={uploadSyncTitle('OmniRoute', omnirouteSync)} style={{ fontSize: 11, margin: 0 }}>OR: {omnirouteMeta.label}</Tag>
              <Tag color={cliproxyMeta.color} style={{ fontSize: 11, margin: 0 }}>CLI: {cliproxyMeta.label}</Tag>
            </div>
          </div>
        )
      },
    })
  } else {
    if (hasUploadCpaAction) {
      columns.push({
        title: 'CPA',
        key: 'cpa_sync',
        width: 110,
        render: (_: any, record: any) => {
          const cpaMeta = uploadSyncMeta(record.cpaSync || {})
          return (
            <Tag color={cpaMeta.color} title={uploadSyncTitle('CPA', record.cpaSync || {})} style={{ fontSize: 11 }}>
              {cpaMeta.label}
            </Tag>
          )
        },
      })
    }
    columns.push({
      title: 'Region / Trial',
      key: 'region_trial',
      width: 110,
      render: (_: any, record: any) => (
        <div style={cellStackStyle}>
          <Text style={{ fontSize: 12 }}>{record.region || '-'}</Text>
          {record.cashier_url ? (
            <Space size={0}>
              <Button type="text" size="small" icon={<CopyOutlined />} onClick={() => copyText(record.cashier_url)} />
              <Button type="text" size="small" icon={<LinkOutlined />} onClick={() => window.open(record.cashier_url, '_blank')} />
            </Space>
          ) : null}
        </div>
      ),
    })
  }

  const statusSyncMenuItems: MenuProps['items'] = [
    {
      key: `probe:${getStatusSyncScope()}`,
      label:
        getStatusSyncScope() === 'selected'
          ? `Sync local status for selected (${selectedRowKeys.length})`
          : `Sync local status for current filter (${total})`,
      disabled: getStatusSyncScope() === 'selected' ? selectedRowKeys.length === 0 : total === 0,
    },
    {
      key: `remote:${getStatusSyncScope()}`,
      label:
        getStatusSyncScope() === 'selected'
          ? `Sync CLIProxyAPI status for selected (${selectedRowKeys.length})`
          : `Sync CLIProxyAPI status for current filter (${total})`,
      disabled: getStatusSyncScope() === 'selected' ? selectedRowKeys.length === 0 : total === 0,
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <Space>
          <Input.Search
            placeholder="Search email..."
            allowClear
            onSearch={(v) => { setPage(1); setSearch(v) }}
            style={{ width: 200 }}
          />
          <Select
            placeholder="Filter by status"
            allowClear
            style={{ width: 120 }}
            onChange={(v) => { setPage(1); setFilterStatus(v) }}
            options={[
              { value: 'registered', label: 'Registered' },
              { value: 'trial', label: 'Trial' },
              { value: 'subscribed', label: 'Subscribed' },
              { value: 'expired', label: 'Expired' },
              { value: 'invalid', label: 'Deactivated' },
            ]}
          />
          <DatePicker
            showTime
            allowClear
            placeholder="Start time"
            onChange={(value) => { setPage(1); setCreatedAtStart(value ? value.toISOString() : '') }}
          />
          <DatePicker
            showTime
            allowClear
            placeholder="End time"
            onChange={(value) => { setPage(1); setCreatedAtEnd(value ? value.toISOString() : '') }}
          />
          <Text type="secondary">{total} accounts</Text>
          {selectedRowKeys.length > 0 && (
            <Text type="success">Selected {selectedRowKeys.length}  items</Text>
          )}
        </Space>
        <Space>
          {currentPlatform === 'chatgpt' && (
            <Dropdown
              trigger={['click']}
              menu={{
                items: statusSyncMenuItems,
                onClick: ({ key }) => {
                  const [kind, scope] = String(key).split(':') as ['probe' | 'remote', 'selected' | 'all']
                  handleBatchStatusSync(kind, scope)
                },
              }}
            >
              <Button
                icon={<SyncOutlined />}
                loading={statusSyncLoading !== ''}
                disabled={total === 0}
              >
                Sync status
              </Button>
            </Dropdown>
          )}
          {currentPlatform === 'chatgpt' && (
            <Popconfirm
              title={
                getBackfillScope() === 'selected'
                  ? `Backfill auth-files for selected ${selectedRowKeys.length} Remote-not-found accounts?`
                  : 'Backfill Remote-not-found accounts with valid local status in the current filter?'
              }
              onConfirm={() => handleCpaBackfill(getBackfillScope())}
              okText="Confirm"
              cancelText="Cancel"
            >
              <Button
                loading={cpaSyncLoading === 'pending' || cpaSyncLoading === 'selected'}
                icon={<UploadOutlined />}
                disabled={getBackfillScope() === 'selected' ? selectedRowKeys.length === 0 : total === 0}
              >
                {backfillButtonLabel()}
              </Button>
            </Popconfirm>
          )}
          {currentPlatform !== 'chatgpt' && hasUploadCpaAction && (
            <Popconfirm
              title={
                getUploadCpaScope() === 'selected'
                  ? `Import selected ${selectedRowKeys.length} accounts into CPA?`
                  : `Import ${total} accounts into CPA?`
              }
              onConfirm={() => handleBatchUploadCpa(getUploadCpaScope())}
              okText="Confirm"
              cancelText="Cancel"
            >
              <Button
                loading={cpaUploadLoading === 'selected' || cpaUploadLoading === 'all'}
                icon={<UploadOutlined />}
                disabled={getUploadCpaScope() === 'selected' ? selectedRowKeys.length === 0 : total === 0}
              >
                {uploadCpaButtonLabel()}
              </Button>
            </Popconfirm>
          )}
          {platformActions.some((item) => item?.id === 'refresh_token') && (
            <Popconfirm
              title={
                selectedRowKeys.length > 0
                  ? `Refresh token for selected ${selectedRowKeys.length} accounts?`
                  : `Refresh token for all ${total} accounts?`
              }
              onConfirm={() => handleBatchAction('refresh_token', 'Refresh token')}
              okText="Confirm"
              cancelText="Cancel"
            >
              <Button
                loading={batchActionLoading === 'refresh_token'}
                icon={<SyncOutlined />}
                disabled={selectedRowKeys.length === 0 && total === 0}
              >
                {selectedRowKeys.length > 0
                  ? `Refresh token selected (${selectedRowKeys.length})`
                  : `Refresh token all (${total})`}
              </Button>
            </Popconfirm>
          )}
          {platformActions.some((item) => item?.id === 'upload_to_omniroute') && (
            <Popconfirm
              title={
                selectedRowKeys.length > 0
                  ? `Upload selected ${selectedRowKeys.length} accounts to OmniRoute?`
                  : `Upload all ${total} accounts to OmniRoute?`
              }
              onConfirm={() => handleBatchAction('upload_to_omniroute', 'Upload to OmniRoute')}
              okText="Confirm"
              cancelText="Cancel"
            >
              <Button
                loading={batchActionLoading === 'upload_to_omniroute'}
                icon={<UploadOutlined />}
                disabled={selectedRowKeys.length === 0 && total === 0}
              >
                {selectedRowKeys.length > 0
                  ? `Upload selected OmniRoute (${selectedRowKeys.length})`
                  : `Upload all OmniRoute (${total})`}
              </Button>
            </Popconfirm>
          )}
          {selectedRowKeys.length > 0 && (
            <Popconfirm
              title={`Delete the selected ${selectedRowKeys.length} accounts?`}
              onConfirm={handleBatchDelete}
              okText="Delete"
              cancelText="Cancel"
              okButtonProps={{ danger: true }}
            >
              <Button danger icon={<DeleteOutlined />}>Delete {selectedRowKeys.length}  items</Button>
            </Popconfirm>
          )}
          <Button icon={<UploadOutlined />} onClick={() => setImportModalOpen(true)}>Import</Button>
          <Button icon={<DownloadOutlined />} onClick={exportCsv} disabled={accounts.length === 0}>Export</Button>
          <Button icon={<PlusOutlined />} onClick={() => setAddModalOpen(true)}>Add</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setRegisterModalOpen(true)}>Register</Button>
          <Button icon={<ReloadOutlined spin={loading} />} onClick={load} />
        </Space>
      </div>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={accounts}
        loading={loading}
        size="middle"
        rowSelection={{
          selectedRowKeys,
          onChange: setSelectedRowKeys,
        }}
        pagination={{ total, current: page, pageSize, showSizeChanger: true, pageSizeOptions: ['20', '50', '100'], onChange: (p, ps) => { setPage(p); setPageSize(ps) } }}
      />

      <Modal
        title={`Register ${currentPlatform}`}
        open={registerModalOpen}
        onCancel={() => { setRegisterModalOpen(false); setTaskId(null); registerForm.resetFields(); }}
        footer={null}
        width={500}
        maskClosable={false}
      >
        {!taskId ? (
          <Form form={registerForm} layout="vertical" onFinish={handleRegister}>
            <Form.Item name="count" label="Register count" initialValue={1} rules={[{ required: true }]}>
              <Input type="number" min={1} />
            </Form.Item>
            <Form.Item name="concurrency" label="Concurrency" initialValue={1} rules={[{ required: true }]}>
              <Input type="number" min={1} />
            </Form.Item>
            <Form.Item name="register_delay_seconds" label="Delay per registration (seconds)" initialValue={0}>
              <InputNumber min={0} precision={1} step={0.5} style={{ width: '100%' }} placeholder="0 = no delay" />
            </Form.Item>
            {currentPlatform === 'chatgpt' && (
              <Form.Item label="ChatGPT Token mode">
                <ChatGPTRegistrationModeSwitch
                  mode={chatgptRegistrationMode}
                  onChange={setChatgptRegistrationMode}
                />
              </Form.Item>
            )}
            <Form.Item>
              <Button type="primary" htmlType="submit" block loading={registerLoading}>
                Start registration
              </Button>
            </Form.Item>
          </Form>
        ) : (
          <TaskLogPanel taskId={taskId} onDone={() => { load(); }} />
        )}
      </Modal>

      <Modal
        title="Add account manually"
        open={addModalOpen}
        onCancel={() => { setAddModalOpen(false); addForm.resetFields(); }}
        onOk={handleAdd}
        okText="OK"
        cancelText="Cancel"
        maskClosable={false}
      >
        <Form form={addForm} layout="vertical">
          <Form.Item name="email" label="Email" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="password" label="Password" rules={[{ required: true }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="token" label="Token">
            <Input />
          </Form.Item>
          <Form.Item name="cashier_url" label="Trial link">
            <Input />
          </Form.Item>
          <Form.Item name="status" label="Status" initialValue="registered">
            <Select
              options={[
                { value: 'registered', label: 'Registered' },
                { value: 'trial', label: 'Trial' },
                { value: 'subscribed', label: 'Subscribed' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Bulk import"
        open={importModalOpen}
        onCancel={() => { setImportModalOpen(false); setImportText(''); }}
        onOk={handleImport}
        okText="OK"
        cancelText="Cancel"
        confirmLoading={importLoading}
        maskClosable={false}
      >
        <p style={{ marginBottom: 8, fontSize: 12, color: '#7a8ba3' }}>
          Each line format: <code style={{ background: 'rgba(255,255,255,0.1)', padding: '2px 4px', borderRadius: 4 }}>email password [cashier_url]</code>
        </p>
        <Input.TextArea
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
          rows={8}
          style={{ fontFamily: 'monospace' }}
        />
      </Modal>

      <Modal
        title="Account details"
        open={detailModalOpen}
        onCancel={() => setDetailModalOpen(false)}
        onOk={handleDetailSave}
        okText="Save"
        cancelText="Cancel"
        maskClosable={false}
        width={760}
        styles={{ body: { maxHeight: '72vh', overflowY: 'auto' } }}
      >
        {currentAccount && (
          <>
            <Form form={detailForm} layout="vertical" initialValues={currentAccount}>
              <Form.Item name="status" label="Status">
                <Select
                  options={[
                    { value: 'registered', label: 'Registered' },
                    { value: 'trial', label: 'Trial' },
                    { value: 'subscribed', label: 'Subscribed' },
                    { value: 'expired', label: 'Expired' },
                    { value: 'invalid', label: 'Deactivated' },
                  ]}
                />
              </Form.Item>
              <Form.Item name="token" label="Access Token">
                <Input.TextArea rows={2} style={{ fontFamily: 'monospace' }} />
              </Form.Item>
            </Form>
            {(() => {
              const rt = getRefreshToken(currentAccount)
              if (!rt) return null
              return (
                <div style={{ marginTop: 8 }}>
                  <div style={{ marginBottom: 4, fontWeight: 500, fontSize: 13 }}>Refresh Token</div>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 8,
                      background: token.colorFillAlter,
                      border: `1px solid ${token.colorBorder}`,
                      borderRadius: token.borderRadius,
                      padding: '8px 10px',
                    }}
                  >
                    <Text
                      style={{ fontFamily: 'monospace', fontSize: 11, wordBreak: 'break-all', flex: 1, userSelect: 'text' }}
                      copyable={{ text: rt, tooltips: ['Copy RT', 'Copied'] }}
                    >
                      {rt}
                    </Text>
                  </div>
                </div>
              )
            })()}
            {(currentPlatform === 'kiro' || currentPlatform === 'kiro2') && currentAccount?.extra ? (
              <DetailSection title="Kiro client information">
                <SummaryField label="Client ID" value={currentAccount.extra?.clientId} code />
                <SummaryField label="Client Secret" value={currentAccount.extra?.clientSecret} code />
              </DetailSection>
            ) : null}
            {currentPlatform === 'chatgpt' ? (
              <DetailSection title="Local probe status">
                {currentAccount.chatgptLocal && Object.keys(currentAccount.chatgptLocal).length > 0 ? (
                  <LocalProbeSummary probe={currentAccount.chatgptLocal} />
                ) : (
                  <Text type="secondary">Not probed yet. Use the Actions menu to run "Probe local status".</Text>
                )}
              </DetailSection>
            ) : null}
            {currentPlatform === 'chatgpt' ? (
              <DetailSection title="CLIProxyAPI status">
                {currentAccount.cliproxySync && Object.keys(currentAccount.cliproxySync).length > 0 ? (
                  <CliproxySyncSummary sync={currentAccount.cliproxySync} />
                ) : (
                  <Text type="secondary">Not synced yet. Use the Actions menu to run "Sync CLIProxyAPI status".</Text>
                )}
              </DetailSection>
            ) : null}
          </>
        )}
      </Modal>
    </div>
  )
}

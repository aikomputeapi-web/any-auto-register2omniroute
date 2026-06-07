import { useEffect, useMemo, useState } from 'react'
import { App, Alert, Button, Card, Form, Input, InputNumber, Popconfirm, Select, Space, Switch, Table, Tag, Typography } from 'antd'
import type { FormInstance } from 'antd'

import { apiFetch } from '@/lib/utils'

type MailImportProviderType = 'applemail' | 'microsoft'
type MailImportSelectionType = MailImportProviderType | 'outlook' | 'hotmail' | 'mailapi'
type MailImportFormProviderType = MailImportProviderType | 'mail_import'

interface MailImportPanelProps {
  form: FormInstance
}

interface MailImportProviderDescriptor {
  type: MailImportProviderType
  label: string
  description: string
  content_placeholder: string
  helper_text: string
  supports_filename: boolean
  filename_label: string
  filename_placeholder: string
  preview_empty_text: string
}

interface MailImportDisplayProvider extends Omit<MailImportProviderDescriptor, 'type'> {
  type: MailImportSelectionType
  apiType: MailImportProviderType
}

interface MailImportSnapshotItem {
  index: number
  email: string
  mailbox: string
  enabled?: boolean | null
  has_oauth?: boolean | null
  account_type?: 'microsoft_oauth' | 'mailapi_url' | null
}

interface MailImportSnapshot {
  type: MailImportProviderType
  label: string
  count: number
  items: MailImportSnapshotItem[]
  truncated: boolean
  filename: string
  path: string
  pool_dir: string
}

interface MailImportSummary {
  total: number
  success: number
  failed: number
}

interface MailImportResult {
  type: MailImportProviderType
  summary: MailImportSummary
  snapshot: MailImportSnapshot
  errors: string[]
  meta: Record<string, unknown>
}

const SUPPORTED_IMPORT_TYPES: MailImportProviderType[] = ['applemail', 'microsoft']
const SUPPORTED_SELECTION_TYPES: MailImportSelectionType[] = ['applemail', 'microsoft', 'outlook', 'hotmail', 'mailapi']

function isSupportedImportType(value: string): value is MailImportProviderType {
  return SUPPORTED_IMPORT_TYPES.includes(value as MailImportProviderType)
}

function isSupportedSelectionType(value: string): value is MailImportSelectionType {
  return SUPPORTED_SELECTION_TYPES.includes(value as MailImportSelectionType)
}

function toImportApiType(value: MailImportSelectionType): MailImportProviderType {
  return value === 'applemail' ? 'applemail' : 'microsoft'
}

function resolveMicrosoftImportType(domain: string) {
  return domain.includes('hotmail') ? 'hotmail' : 'outlook'
}

function resolvePreferredImportType(
  currentMailProvider: string,
  mailImportSource: string,
  luckmailEmailType: string,
  luckmailDomain: string,
  applemailPoolFile: string,
): MailImportSelectionType {
  if (currentMailProvider === 'mail_import') {
    return mailImportSource === 'applemail' ? 'applemail' : resolveMicrosoftImportType(String(luckmailDomain || '').trim().toLowerCase())
  }
  if (currentMailProvider === 'applemail') return 'applemail'
  if (currentMailProvider === 'microsoft' || currentMailProvider === 'outlook') {
    return resolveMicrosoftImportType(String(luckmailDomain || '').trim().toLowerCase())
  }

  const normalizedLuckmailType = String(luckmailEmailType || '').trim().toLowerCase()
  const normalizedLuckmailDomain = String(luckmailDomain || '').trim().toLowerCase()
  const isMicrosoftMailbox =
    normalizedLuckmailType.startsWith('ms_')
    || normalizedLuckmailDomain.includes('outlook')
    || normalizedLuckmailDomain.includes('hotmail')

  if (isMicrosoftMailbox) {
    return resolveMicrosoftImportType(normalizedLuckmailDomain)
  }

  if (String(applemailPoolFile || '').trim()) {
    return 'applemail'
  }

  return 'outlook'
}

function buildDisplayProviders(providers: MailImportProviderDescriptor[]) {
  const items: MailImportDisplayProvider[] = []

  for (const provider of providers) {
    if (provider.type === 'applemail') {
      items.push({
        ...provider,
        type: 'applemail',
        apiType: 'applemail',
        label: 'AppleMail / Apple Mail',
      })
      continue
    }

    items.push(
      {
        ...provider,
        type: 'outlook',
        apiType: 'microsoft',
        label: 'Outlook',
        description: 'Import the local Outlook account pool, supporting mixed import (OAuth / MailAPI URL); runtime automatically selects Graph/IMAP or MailAPI URL polling based on account type.',
        helper_text: 'Supports automatic detection: email----password----client_id----refresh_token or email----mailapi_url; this view only shows @outlook OAuth accounts.',
        content_placeholder: 'example@outlook.com----password----client_id----refresh_token',
        preview_empty_text: 'There are no imported Outlook accounts available for preview yet.',
      },
      {
        ...provider,
        type: 'hotmail',
        apiType: 'microsoft',
        label: 'Hotmail',
        description: 'Import the local Hotmail account pool, supporting mixed import (OAuth / MailAPI URL); runtime automatically selects Graph/IMAP or MailAPI URL polling based on account type.',
        helper_text: 'Supports automatic detection: email----password----client_id----refresh_token or email----mailapi_url; this view only shows @hotmail OAuth accounts.',
        content_placeholder: 'example@hotmail.com----password----client_id----refresh_token',
        preview_empty_text: 'There are no imported Hotmail accounts available for preview yet.',
      },
      {
        ...provider,
        type: 'mailapi',
        apiType: 'microsoft',
        label: 'MailAPI URL',
        description: 'Import the MailAPI URL account pool (email----mailapi_url); runtime polls the web page content through the URL to extract verification codes.',
        helper_text: 'Supports mixed import. This view only shows accounts with account_type=mailapi_url.',
        content_placeholder: 'example@hotmail.com----https://mailapi.icu/key?type=html&orderNo=xxxxxxxx',
        preview_empty_text: 'There are no imported MailAPI URL accounts available for preview yet.',
      },
    )
  }

  return items
}

function matchesSelectionType(
  selectionType: MailImportSelectionType,
  email: string,
  accountType?: string | null,
) {
  const domain = String(email.split('@')[1] || '').trim().toLowerCase()
  const normalizedType = String(accountType || 'microsoft_oauth').trim().toLowerCase()
  if (selectionType === 'mailapi') return normalizedType === 'mailapi_url'
  if (selectionType === 'hotmail') return normalizedType !== 'mailapi_url' && domain.includes('hotmail')
  if (selectionType === 'outlook') return normalizedType !== 'mailapi_url' && domain.includes('outlook')
  return true
}

function filterSnapshotBySelection(
  snapshot: MailImportSnapshot | null,
  selectionType: MailImportSelectionType,
) {
  if (!snapshot || selectionType === 'applemail' || snapshot.type !== 'microsoft') {
    return snapshot
  }

  return {
    ...snapshot,
    items: snapshot.items.filter((item) => matchesSelectionType(selectionType, item.email, item.account_type)),
  }
}

function buildImportSuccessMessage(result: MailImportResult) {
  if (result.type === 'applemail') {
    const fileLabel = result.snapshot.filename ? `, bound ${result.snapshot.filename}` : ''
    return `Import successful, total ${result.summary.success} mailboxes${fileLabel}`
  }
  return `Import completed: success ${result.summary.success} / failed ${result.summary.failed}`
}

function buildResultMessage(result: MailImportResult) {
  if (result.type === 'applemail') {
    return `Import completed: success ${result.summary.success} / failed ${result.summary.failed}`
  }
  return `Import completed: success ${result.summary.success} / failed ${result.summary.failed}`
}

export default function MailImportPanel({ form }: MailImportPanelProps) {
  const { message } = App.useApp()
  const currentMailProvider = String(Form.useWatch('mail_provider', form) || '') as MailImportFormProviderType
  const currentMailImportSource = String(Form.useWatch('mail_import_source', form) || 'microsoft')
  const watchedPoolDir = String(Form.useWatch('applemail_pool_dir', form) || 'mail')
  const watchedPoolFile = String(Form.useWatch('applemail_pool_file', form) || '')
  const watchedLuckmailEmailType = String(Form.useWatch('luckmail_email_type', form) || '')
  const watchedLuckmailDomain = String(Form.useWatch('luckmail_domain', form) || '')

  const [providers, setProviders] = useState<MailImportDisplayProvider[]>([])
  const [selectedType, setSelectedType] = useState<MailImportSelectionType>('outlook')
  const [content, setContent] = useState('')
  const [filename, setFilename] = useState('')
  const [importing, setImporting] = useState(false)
  const [deletingEmail, setDeletingEmail] = useState('')
  const [batchDeleting, setBatchDeleting] = useState(false)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [loadingProviders, setLoadingProviders] = useState(false)
  const [loadingSnapshot, setLoadingSnapshot] = useState(false)
  const [rawSnapshot, setRawSnapshot] = useState<MailImportSnapshot | null>(null)
  const [result, setResult] = useState<MailImportResult | null>(null)
  const [aliasSplitEnabled, setAliasSplitEnabled] = useState(false)
  const [aliasSplitCount, setAliasSplitCount] = useState(5)
  const [aliasIncludeOriginal, setAliasIncludeOriginal] = useState(false)

  const providerMap = useMemo(
    () => new Map(providers.map((provider) => [provider.type, provider])),
    [providers],
  )
  const selectedProvider = providerMap.get(selectedType) ?? null
  const selectedApiType = selectedProvider?.apiType ?? toImportApiType(selectedType)
  const supportsAliasSplit = selectedApiType === 'microsoft'
  const preferredImportType = useMemo(
    () => resolvePreferredImportType(
      currentMailProvider,
      currentMailImportSource,
      watchedLuckmailEmailType,
      watchedLuckmailDomain,
      watchedPoolFile,
    ),
    [currentMailImportSource, currentMailProvider, watchedLuckmailDomain, watchedLuckmailEmailType, watchedPoolFile],
  )
  const snapshot = useMemo(
    () => filterSnapshotBySelection(rawSnapshot, selectedType),
    [rawSnapshot, selectedType],
  )
  const tableData = useMemo(
    () => (snapshot?.items || []).map((item) => ({
      ...item,
      key: `${item.email}::${item.mailbox || ''}`,
    })),
    [snapshot],
  )

  const loadProviders = async () => {
    setLoadingProviders(true)
    try {
      const data = await apiFetch('/mail-imports/providers') as { items?: MailImportProviderDescriptor[] }
      const items = Array.isArray(data.items) ? data.items.filter((item) => isSupportedImportType(item.type)) : []
      const displayProviders = buildDisplayProviders(items)
      setProviders(displayProviders)

      if (isSupportedSelectionType(preferredImportType) && displayProviders.some((item) => item.type === preferredImportType)) {
        setSelectedType(preferredImportType)
      } else if (displayProviders.length > 0) {
        setSelectedType(displayProviders[0].type)
      }
    } catch (error) {
      const detail = error instanceof Error ? error.message : 'Failed to load mailbox import configuration'
      message.error(detail)
    } finally {
      setLoadingProviders(false)
    }
  }

  const loadSnapshot = async (providerType: MailImportSelectionType) => {
    setLoadingSnapshot(true)
    try {
      const apiType = toImportApiType(providerType)
      const params = new URLSearchParams({ type: apiType })
      if (apiType === 'applemail') {
        if (watchedPoolDir.trim()) {
          params.set('pool_dir', watchedPoolDir.trim())
        }
        if (watchedPoolFile.trim()) {
          params.set('pool_file', watchedPoolFile.trim())
        }
      }
      const nextSnapshot = await apiFetch(`/mail-imports/snapshot?${params.toString()}`) as MailImportSnapshot
      setRawSnapshot(nextSnapshot)
    } catch {
      setRawSnapshot(null)
    } finally {
      setLoadingSnapshot(false)
    }
  }

  useEffect(() => {
    void loadProviders()
  }, [])

  useEffect(() => {
    if (providerMap.has(preferredImportType)) {
      setSelectedType(preferredImportType)
    }
  }, [preferredImportType, providerMap])

  useEffect(() => {
    if (!selectedProvider) return
    void loadSnapshot(selectedType)
  }, [selectedProvider, selectedType, watchedPoolDir, watchedPoolFile])

  useEffect(() => {
    setSelectedRowKeys([])
  }, [selectedType, rawSnapshot])

  const handleImport = async () => {
    const payload = content.trim()
    if (!payload) {
      message.error('Please enter import content')
      return
    }

    setImporting(true)
    try {
      const apiType = toImportApiType(selectedType)
      const body: Record<string, unknown> = {
        type: apiType,
        content: payload,
        enabled: true,
        bind_to_config: true,
      }

      if (apiType === 'applemail') {
        body.filename = filename.trim()
        body.pool_dir = String(form.getFieldValue('applemail_pool_dir') || 'mail').trim() || 'mail'
      } else {
        body.alias_split_enabled = aliasSplitEnabled
        body.alias_split_count = aliasSplitCount
        body.alias_include_original = aliasIncludeOriginal
      }

      const response = await apiFetch('/mail-imports', {
        method: 'POST',
        body: JSON.stringify(body),
      }) as MailImportResult

      setResult(response)
      setRawSnapshot(response.snapshot)
      setContent('')
      setFilename('')

      if (response.type === 'applemail') {
        form.setFieldsValue({
          mail_provider: 'mail_import',
          mail_import_source: 'applemail',
          applemail_pool_dir: response.snapshot.pool_dir,
          applemail_pool_file: response.snapshot.filename,
        })
      } else if (response.type === 'microsoft') {
        form.setFieldsValue({
          mail_provider: 'mail_import',
          mail_import_source: 'microsoft',
        })
      }

      message.success(buildImportSuccessMessage(response))
    } catch (error) {
      const detail = error instanceof Error ? error.message : 'Mailbox import failed'
      message.error(detail)
    } finally {
      setImporting(false)
    }
  }

  const handleTypeChange = (value: MailImportSelectionType) => {
    setSelectedType(value)
    form.setFieldsValue({
      mail_provider: 'mail_import',
      mail_import_source: value === 'applemail' ? 'applemail' : 'microsoft',
    })
  }

  const handleDelete = async (item: MailImportSnapshotItem) => {
    const apiType = toImportApiType(selectedType)
    const email = String(item.email || '').trim()
    if (!email) return

    setDeletingEmail(email)
    try {
      const body: Record<string, unknown> = {
        type: apiType,
        email,
      }

      if (apiType === 'applemail') {
        body.mailbox = item.mailbox || ''
        body.pool_dir = String(form.getFieldValue('applemail_pool_dir') || 'mail').trim() || 'mail'
        body.pool_file = String(form.getFieldValue('applemail_pool_file') || '').trim()
      }

      const response = await apiFetch('/mail-imports/delete', {
        method: 'POST',
        body: JSON.stringify(body),
      }) as MailImportResult

      setResult(response)
      setRawSnapshot(response.snapshot)
      setSelectedRowKeys([])
      message.success(`Deleted ${email}`)
    } catch (error) {
      const detail = error instanceof Error ? error.message : 'Delete failed'
      message.error(detail)
    } finally {
      setDeletingEmail('')
    }
  }

  const handleBatchDelete = async () => {
    if (!selectedRowKeys.length) {
      message.warning('Please select the mailboxes to delete first')
      return
    }

    const selectedItems = tableData.filter((item) => selectedRowKeys.includes(item.key))
    if (!selectedItems.length) {
      message.warning('No mailboxes found to delete')
      return
    }

    const apiType = toImportApiType(selectedType)
    setBatchDeleting(true)
    try {
      const body: Record<string, unknown> = {
        type: apiType,
        items: selectedItems.map((item) => ({
          email: item.email,
          mailbox: item.mailbox || '',
        })),
      }

      if (apiType === 'applemail') {
        body.pool_dir = String(form.getFieldValue('applemail_pool_dir') || 'mail').trim() || 'mail'
        body.pool_file = String(form.getFieldValue('applemail_pool_file') || '').trim()
      }

      const response = await apiFetch('/mail-imports/batch-delete', {
        method: 'POST',
        body: JSON.stringify(body),
      }) as MailImportResult

      setResult(response)
      setRawSnapshot(response.snapshot)
      setSelectedRowKeys([])
      message.success(`Batch delete completed: success ${response.summary.success} / failed ${response.summary.failed}`)
    } catch (error) {
      const detail = error instanceof Error ? error.message : 'Batch delete failed'
      const shouldFallbackToSingleDelete = /405|404|Method Not Allowed|Not Found/i.test(detail)

      if (!shouldFallbackToSingleDelete) {
        message.error(detail)
        return
      }

      let success = 0
      let failed = 0
      const errors: string[] = []

      for (const item of selectedItems) {
        try {
          const body: Record<string, unknown> = {
            type: apiType,
            email: item.email,
          }

          if (apiType === 'applemail') {
            body.mailbox = item.mailbox || ''
            body.pool_dir = String(form.getFieldValue('applemail_pool_dir') || 'mail').trim() || 'mail'
            body.pool_file = String(form.getFieldValue('applemail_pool_file') || '').trim()
          }

          const response = await apiFetch('/mail-imports/delete', {
            method: 'POST',
            body: JSON.stringify(body),
          }) as MailImportResult

          setResult(response)
          setRawSnapshot(response.snapshot)
          success += 1
        } catch (singleError) {
          failed += 1
          errors.push(singleError instanceof Error ? singleError.message : `Delete failed: ${item.email}`)
        }
      }

      setSelectedRowKeys([])
      if (errors.length) {
        message.warning(`Batch delete fell back to single-item deletion: success ${success} / failed ${failed}`)
        setResult((prev) => prev ? {
          ...prev,
          errors,
          summary: { total: success + failed, success, failed },
        } : prev)
      } else {
        message.success(`Batch delete fell back to single-item deletion: success ${success} / failed ${failed}`)
      }
    } finally {
      setBatchDeleting(false)
    }
  }

  const columns = useMemo(() => {
    const baseColumns = [
      {
        title: '#',
        dataIndex: 'index',
        key: 'index',
        width: 72,
      },
      {
        title: 'Email',
        dataIndex: 'email',
        key: 'email',
      },
    ]

    if (selectedType === 'applemail') {
      baseColumns.push({
        title: 'Email folder',
        dataIndex: 'mailbox',
        key: 'mailbox',
        width: 140,
        render: (value: string) => <Tag>{value || 'INBOX'}</Tag>,
      } as never)
    } else {
      baseColumns.push(
        {
          title: 'Type',
          dataIndex: 'account_type',
          key: 'account_type',
          width: 120,
          render: (value: string | null | undefined) => {
            const isMailApi = String(value || '').trim().toLowerCase() === 'mailapi_url'
            return <Tag color={isMailApi ? 'purple' : 'blue'}>{isMailApi ? 'MailAPI URL' : 'OAuth'}</Tag>
          },
        } as never,
        {
          title: 'Status',
          dataIndex: 'enabled',
          key: 'enabled',
          width: 100,
          render: (value: boolean | null | undefined) => (
            <Tag color={value ? 'green' : 'default'}>{value ? 'Enabled' : 'Disabled'}</Tag>
          ),
        } as never,
        {
          title: 'Auth',
          dataIndex: 'has_oauth',
          key: 'has_oauth',
          width: 100,
          render: (value: boolean | null | undefined) => (
            <Tag color={value ? 'blue' : 'default'}>{value ? 'OAuth' : 'Password'}</Tag>
          ),
        } as never,
      )
    }

    baseColumns.push({
      title: 'Actions',
      key: 'action',
      width: 90,
      render: (_: unknown, item: MailImportSnapshotItem) => (
        <Popconfirm
          title="Delete this email?"
          description={item.email}
          okText="Delete"
          cancelText="Cancel"
          okButtonProps={{ danger: true, loading: deletingEmail === item.email }}
          onConfirm={() => void handleDelete(item)}
        >
          <Button
            danger
            type="link"
            size="small"
            loading={deletingEmail === item.email}
            style={{ paddingInline: 0 }}
          >
            Delete
          </Button>
        </Popconfirm>
      ),
    } as never)

    return baseColumns
  }, [deletingEmail, selectedType, tableData])

  return (
    <Card
      title="Email import"
      extra={(
        <Select
          value={selectedType}
          onChange={handleTypeChange}
          loading={loadingProviders}
          style={{ width: 240 }}
          options={providers.map((provider) => ({
            label: provider.label,
            value: provider.type,
          }))}
        />
      )}
      style={{ marginBottom: 16 }}
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <Typography.Text type="secondary">
          {selectedProvider?.description || 'Use the unified import interface to load content into the corresponding email account pool.'}
        </Typography.Text>
        {selectedProvider?.helper_text ? (
          <Typography.Text type="secondary">{selectedProvider.helper_text}</Typography.Text>
        ) : null}

        {selectedProvider?.supports_filename ? (
          <Form.Item label={selectedProvider.filename_label || 'Filename'} style={{ marginBottom: 0 }}>
            <Input
              value={filename}
              onChange={(event) => setFilename(event.target.value)}
              placeholder={selectedProvider.filename_placeholder}
            />
          </Form.Item>
        ) : null}

        {supportsAliasSplit ? (
          <div
            style={{
              border: '1px dashed rgba(127,127,127,0.35)',
              borderRadius: 8,
              padding: 12,
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
            }}
          >
            <Space align="center">
              <Typography.Text strong>Email alias splitting</Typography.Text>
              <Switch checked={aliasSplitEnabled} onChange={setAliasSplitEnabled} />
              <Typography.Text type="secondary">
                Disabled by default; when enabled, each original email generates a random 6-character English alias.
              </Typography.Text>
            </Space>
            {aliasSplitEnabled ? (
              <Space align="center" wrap>
                <Typography.Text>Aliases per original email</Typography.Text>
                <InputNumber
                  min={1}
                  max={5}
                  value={aliasSplitCount}
                  onChange={(value) => setAliasSplitCount(Math.max(1, Math.min(5, Number(value || 5))))}
                />
                <Typography.Text type="secondary">(1~5)</Typography.Text>
                <Typography.Text style={{ marginLeft: 16 }}>Include original email</Typography.Text>
                <Switch checked={aliasIncludeOriginal} onChange={setAliasIncludeOriginal} />
              </Space>
            ) : null}
          </div>
        ) : null}

        <Input.TextArea
          value={content}
          onChange={(event) => setContent(event.target.value)}
          rows={10}
          placeholder={selectedProvider?.content_placeholder || ''}
          style={{ fontFamily: 'monospace' }}
        />

        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Button
            danger
            onClick={() => {
              setContent('')
              setFilename('')
              setResult(null)
            }}
          >
            Clear
          </Button>
          <Space>
            <Button onClick={() => void loadSnapshot(selectedType)} loading={loadingSnapshot}>
              Refresh preview
            </Button>
            <Button type="primary" onClick={handleImport} loading={importing}>
              Confirm import
            </Button>
          </Space>
        </Space>

        {result ? (
          <Alert
            type={result.summary.failed ? 'warning' : 'success'}
            showIcon
            message={buildResultMessage(result)}
            description={result.errors.length ? (
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{result.errors.join('\n')}</pre>
            ) : undefined}
          />
        ) : null}

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <Tag color="blue">
            {selectedType === 'applemail'
              ? `Imported: ${snapshot?.count || 0} mailboxes`
              : `Current preview matches: ${snapshot?.items.length || 0}${rawSnapshot?.truncated ? ` / total pool ${rawSnapshot?.count || 0}` : ''}`}
          </Tag>
          {selectedType === 'applemail' && snapshot?.filename ? (
            <Typography.Text type="secondary">Current file: {snapshot.filename}</Typography.Text>
          ) : null}
          {snapshot?.items?.length ? (
            <Popconfirm
              title={`Delete the ${selectedRowKeys.length} selected mailboxes?`}
              okText="Batch delete"
              cancelText="Cancel"
              okButtonProps={{ danger: true, loading: batchDeleting }}
              onConfirm={() => void handleBatchDelete()}
              disabled={!selectedRowKeys.length}
            >
              <Button danger disabled={!selectedRowKeys.length} loading={batchDeleting}>
                Batch delete
              </Button>
            </Popconfirm>
          ) : null}
        </div>
        {snapshot?.items?.length ? (
          <Table
            rowSelection={{
              selectedRowKeys,
              onChange: setSelectedRowKeys,
            }}
            columns={columns}
            dataSource={tableData}
            size="small"
            pagination={false}
            scroll={{ y: 320 }}
          />
        ) : (
          <div
            style={{
              border: '1px solid rgba(127,127,127,0.25)',
              borderRadius: 8,
              padding: 12,
              background: 'rgba(127,127,127,0.06)',
              minHeight: 88,
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <Typography.Text type="secondary">
              {selectedProvider?.preview_empty_text || 'There is no import content available for preview yet.'}
            </Typography.Text>
          </div>
        )}

        {snapshot?.truncated ? (
          <Typography.Text type="secondary">The preview shows only the first 100 records; the stored content is authoritative.</Typography.Text>
        ) : null}
      </Space>
    </Card>
  )
}

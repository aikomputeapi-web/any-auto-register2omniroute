import { useEffect, useState } from 'react'
import {
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Button,
  Checkbox,
  Tag,
  Space,
  Typography,
  Descriptions,
} from 'antd'
import {
  PlayCircleOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
} from '@ant-design/icons'
import { ChatGPTRegistrationModeSwitch } from '@/components/ChatGPTRegistrationModeSwitch'
import { TaskLogPanel } from '@/components/TaskLogPanel'
import { usePersistentChatGPTRegistrationMode } from '@/hooks/usePersistentChatGPTRegistrationMode'
import { parseBooleanConfigValue } from '@/lib/configValueParsers'
import { buildChatGPTRegistrationRequestAdapter } from '@/lib/chatgptRegistrationRequestAdapter'
import { getExecutorOptions, normalizeExecutorForPlatform } from '@/lib/platformExecutorOptions'
import { apiFetch } from '@/lib/utils'

const { Text } = Typography

function resolveEffectiveMailProvider(mailProvider: string, mailImportSource: string) {
  if (mailProvider !== 'mail_import') return mailProvider
  return mailImportSource === 'applemail' ? 'applemail' : 'microsoft'
}

export default function RegisterTaskPage() {
  const [form] = Form.useForm()
  const [task, setTask] = useState<any>(null)
  const [polling, setPolling] = useState(false)
  const { mode: chatgptRegistrationMode, setMode: setChatgptRegistrationMode } =
    usePersistentChatGPTRegistrationMode()

  useEffect(() => {
    apiFetch('/config').then((cfg) => {
      const currentPlatform = form.getFieldValue('platform') || 'chatgpt'
      const configMailProvider = String(cfg.mail_provider || 'luckmail')
      const isMailImportProvider = configMailProvider === 'microsoft' || configMailProvider === 'outlook' || configMailProvider === 'applemail'
      form.setFieldsValue({
        executor_type: normalizeExecutorForPlatform(currentPlatform, cfg.default_executor),
        captcha_solver: cfg.default_captcha_solver || 'yescaptcha',
        mail_provider: isMailImportProvider ? 'mail_import' : configMailProvider,
        mail_import_source: configMailProvider === 'applemail' ? 'applemail' : 'microsoft',
        applemail_base_url: cfg.applemail_base_url || 'https://www.appleemail.top',
        applemail_pool_dir: cfg.applemail_pool_dir || 'mail',
        applemail_pool_file: cfg.applemail_pool_file || '',
        applemail_mailboxes: cfg.applemail_mailboxes || 'INBOX,Junk',
        yescaptcha_key: cfg.yescaptcha_key || '',
        moemail_api_url: cfg.moemail_api_url || '',
        moemail_api_key: cfg.moemail_api_key || '',
        skymail_api_base: cfg.skymail_api_base || 'https://api.skymail.ink',
        skymail_token: cfg.skymail_token || '',
        skymail_domain: cfg.skymail_domain || '',
        cloudmail_api_base: cfg.cloudmail_api_base || '',
        cloudmail_admin_email: cfg.cloudmail_admin_email || '',
        cloudmail_admin_password: cfg.cloudmail_admin_password || '',
        cloudmail_domain: cfg.cloudmail_domain || '',
        cloudmail_subdomain: cfg.cloudmail_subdomain || '',
        cloudmail_timeout: cfg.cloudmail_timeout || 30,
        outlook_backend: cfg.outlook_backend || 'graph',
        laoudo_auth: cfg.laoudo_auth || '',
        laoudo_email: cfg.laoudo_email || '',
        laoudo_account_id: cfg.laoudo_account_id || '',
        gptmail_base_url: cfg.gptmail_base_url || 'https://mail.chatgpt.org.uk',
        gptmail_api_key: cfg.gptmail_api_key || '',
        gptmail_domain: cfg.gptmail_domain || '',
        opentrashmail_api_url: cfg.opentrashmail_api_url || '',
        opentrashmail_domain: cfg.opentrashmail_domain || '',
        opentrashmail_password: cfg.opentrashmail_password || '',
        maliapi_base_url: cfg.maliapi_base_url || 'https://maliapi.215.im/v1',
        maliapi_api_key: cfg.maliapi_api_key || '',
        maliapi_domain: cfg.maliapi_domain || '',
        maliapi_auto_domain_strategy: cfg.maliapi_auto_domain_strategy || 'balanced',
        duckmail_api_url: cfg.duckmail_api_url || '',
        duckmail_provider_url: cfg.duckmail_provider_url || '',
        duckmail_bearer: cfg.duckmail_bearer || '',
        freemail_api_url: cfg.freemail_api_url || '',
        freemail_admin_token: cfg.freemail_admin_token || '',
        freemail_username: cfg.freemail_username || '',
        freemail_password: cfg.freemail_password || '',
        freemail_domain: cfg.freemail_domain || '',
        cfworker_api_url: cfg.cfworker_api_url || '',
        cfworker_admin_token: cfg.cfworker_admin_token || '',
        cfworker_custom_auth: cfg.cfworker_custom_auth || '',
        cfworker_domain_override: '',
        cfworker_subdomain: cfg.cfworker_subdomain || '',
        cfworker_random_subdomain: parseBooleanConfigValue(cfg.cfworker_random_subdomain),
        cfworker_random_name_subdomain: parseBooleanConfigValue(cfg.cfworker_random_name_subdomain),
        cfworker_fingerprint: cfg.cfworker_fingerprint || '',
        smstome_cookie: cfg.smstome_cookie || '',
        smstome_country_slugs: cfg.smstome_country_slugs || '',
        smstome_phone_attempts: cfg.smstome_phone_attempts || '',
        smstome_otp_timeout_seconds: cfg.smstome_otp_timeout_seconds || '',
        smstome_poll_interval_seconds: cfg.smstome_poll_interval_seconds || '',
        smstome_sync_max_pages_per_country: cfg.smstome_sync_max_pages_per_country || '',
        luckmail_base_url: cfg.luckmail_base_url || 'https://mails.luckyous.com/',
        luckmail_api_key: cfg.luckmail_api_key || '',
        luckmail_email_type: cfg.luckmail_email_type || '',
        luckmail_domain: cfg.luckmail_domain || '',
        imap_catchall_server: cfg.imap_catchall_server || '',
        imap_catchall_port: cfg.imap_catchall_port || '993',
        imap_catchall_username: cfg.imap_catchall_username || '',
        imap_catchall_password: cfg.imap_catchall_password || '',
        imap_catchall_domain: cfg.imap_catchall_domain || '',
        imap_catchall_folders: cfg.imap_catchall_folders || 'INBOX',
        phone_number: cfg.default_phone_number || '',
      })
    })
  }, [form])

  const submit = async () => {
    const values = await form.validateFields()
    const effectiveMailProvider = resolveEffectiveMailProvider(values.mail_provider, values.mail_import_source)
    const registerExtra = {
      mail_provider: effectiveMailProvider,
      applemail_base_url: values.applemail_base_url,
      applemail_pool_dir: values.applemail_pool_dir,
      applemail_pool_file: values.applemail_pool_file,
      applemail_mailboxes: values.applemail_mailboxes,
      laoudo_auth: values.laoudo_auth,
      laoudo_email: values.laoudo_email,
      laoudo_account_id: values.laoudo_account_id,
      gptmail_base_url: values.gptmail_base_url,
      gptmail_api_key: values.gptmail_api_key,
      gptmail_domain: values.gptmail_domain,
      opentrashmail_api_url: values.opentrashmail_api_url,
      opentrashmail_domain: values.opentrashmail_domain,
      opentrashmail_password: values.opentrashmail_password,
      maliapi_base_url: values.maliapi_base_url,
      maliapi_api_key: values.maliapi_api_key,
      maliapi_domain: values.maliapi_domain,
      maliapi_auto_domain_strategy: values.maliapi_auto_domain_strategy,
      moemail_api_url: values.moemail_api_url,
      moemail_api_key: values.moemail_api_key,
      skymail_api_base: values.skymail_api_base,
      skymail_token: values.skymail_token,
      skymail_domain: values.skymail_domain,
      cloudmail_api_base: values.cloudmail_api_base,
      cloudmail_admin_email: values.cloudmail_admin_email,
      cloudmail_admin_password: values.cloudmail_admin_password,
      cloudmail_domain: values.cloudmail_domain,
      cloudmail_subdomain: values.cloudmail_subdomain,
      cloudmail_timeout: values.cloudmail_timeout,
      outlook_backend: values.outlook_backend,
      duckmail_api_url: values.duckmail_api_url,
      duckmail_provider_url: values.duckmail_provider_url,
      duckmail_bearer: values.duckmail_bearer,
      freemail_api_url: values.freemail_api_url,
      freemail_admin_token: values.freemail_admin_token,
      freemail_username: values.freemail_username,
      freemail_password: values.freemail_password,
      freemail_domain: values.freemail_domain,
      cfworker_api_url: values.cfworker_api_url,
      cfworker_admin_token: values.cfworker_admin_token,
      cfworker_custom_auth: values.cfworker_custom_auth,
      cfworker_domain_override: values.cfworker_domain_override,
      cfworker_subdomain: values.cfworker_subdomain,
      cfworker_random_subdomain: values.cfworker_random_subdomain,
      cfworker_random_name_subdomain: values.cfworker_random_name_subdomain,
      cfworker_fingerprint: values.cfworker_fingerprint,
      smstome_cookie: values.smstome_cookie,
      smstome_country_slugs: values.smstome_country_slugs,
      smstome_phone_attempts: values.smstome_phone_attempts,
      smstome_otp_timeout_seconds: values.smstome_otp_timeout_seconds,
      smstome_poll_interval_seconds: values.smstome_poll_interval_seconds,
      smstome_sync_max_pages_per_country: values.smstome_sync_max_pages_per_country,
      luckmail_base_url: values.luckmail_base_url,
      luckmail_api_key: values.luckmail_api_key,
      luckmail_email_type: values.luckmail_email_type,
      luckmail_domain: values.luckmail_domain,
      imap_catchall_server: values.imap_catchall_server,
      imap_catchall_port: values.imap_catchall_port,
      imap_catchall_username: values.imap_catchall_username,
      imap_catchall_password: values.imap_catchall_password,
      imap_catchall_domain: values.imap_catchall_domain,
      imap_catchall_folders: values.imap_catchall_folders,
      yescaptcha_key: values.yescaptcha_key,
      solver_url: values.solver_url,
      phone_number: values.phone_number,
    }
    const chatgptRegistrationRequestAdapter =
      buildChatGPTRegistrationRequestAdapter(
        values.platform,
        chatgptRegistrationMode,
      )
    const adaptedRegisterExtra = chatgptRegistrationRequestAdapter
      ? chatgptRegistrationRequestAdapter.extendExtra(registerExtra)
      : registerExtra

    const res = await apiFetch('/tasks/register', {
      method: 'POST',
      body: JSON.stringify({
        platform: values.platform,
        email: values.email || null,
        password: values.password || null,
        count: values.count,
        concurrency: values.concurrency,
        register_delay_seconds: values.register_delay_seconds || 0,
        proxy: values.proxy || null,
        executor_type: values.executor_type,
        captcha_solver: values.captcha_solver,
        extra: adaptedRegisterExtra,
      }),
    })
    setTask(res)
    setPolling(true)
    pollTask(res.task_id)
  }

  const pollTask = async (id: string) => {
    const interval = setInterval(async () => {
      const t = await apiFetch(`/tasks/${id}`)
      setTask(t)
      if (t.status === 'done' || t.status === 'failed' || t.status === 'stopped') {
        clearInterval(interval)
        setPolling(false)
        if (t.cashier_urls && t.cashier_urls.length > 0) {
          t.cashier_urls.forEach((url: string) => window.open(url, '_blank'))
        }
      }
    }, 2000)
  }

  const mailProviderRaw = Form.useWatch('mail_provider', form)
  const mailImportSource = Form.useWatch('mail_import_source', form)
  const mailProvider = resolveEffectiveMailProvider(String(mailProviderRaw || ''), String(mailImportSource || 'microsoft'))
  const captchaSolver = Form.useWatch('captcha_solver', form)
  const platform = Form.useWatch('platform', form)
  const executorOptions = getExecutorOptions(platform)

  useEffect(() => {
    const currentExecutor = form.getFieldValue('executor_type')
    const normalizedExecutor = normalizeExecutorForPlatform(platform, currentExecutor)
    if (currentExecutor !== normalizedExecutor) {
      form.setFieldValue('executor_type', normalizedExecutor)
    }
  }, [form, platform])

  return (
    <div style={{ maxWidth: 800 }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 24, fontWeight: 'bold', margin: 0 }}>Registration Task</h1>
        <p style={{ color: '#7a8ba3', marginTop: 4 }}>Automated account creation task</p>
      </div>

      <Form form={form} layout="vertical" onFinish={submit} initialValues={{
        platform: 'chatgpt',
        executor_type: 'protocol',
        captcha_solver: 'yescaptcha',
        mail_provider: 'luckmail',
        mail_import_source: 'microsoft',
        applemail_base_url: 'https://www.appleemail.top',
        applemail_pool_dir: 'mail',
        applemail_mailboxes: 'INBOX,Junk',
        outlook_backend: 'graph',
        gptmail_base_url: 'https://mail.chatgpt.org.uk',
        cloudmail_timeout: 30,
        count: 1,
        concurrency: 1,
        register_delay_seconds: 0,
        maliapi_base_url: 'https://maliapi.215.im/v1',
        maliapi_auto_domain_strategy: 'balanced',
        solver_url: 'http://localhost:8889',
        phone_number: '',
      }}>
        <Card title="Basic Configuration" style={{ marginBottom: 16 }}>
          <Form.Item name="platform" label="Platform" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'chatgpt', label: 'ChatGPT' },
                { value: 'cloudflare', label: 'Cloudflare' },
                { value: 'cursor', label: 'Cursor' },
                { value: 'kiro', label: 'Kiro' },
                { value: 'kiro2', label: 'Kiro 2' },
                { value: 'grok', label: 'Grok' },
                { value: 'tavily', label: 'Tavily' },
                { value: 'openblocklabs', label: 'OpenBlockLabs' },
                { value: 'cerebras', label: 'Cerebras' },
              ]}
            />
          </Form.Item>
          <Form.Item name="executor_type" label="Executor" rules={[{ required: true }]}>
            <Select options={executorOptions} />
          </Form.Item>
          <Form.Item name="captcha_solver" label="Captcha" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'yescaptcha', label: 'YesCaptcha' },
                { value: 'local_solver', label: 'Local Solver (Camoufox)' },
                { value: 'manual', label: 'Manual' },
              ]}
            />
          </Form.Item>
          <Space style={{ width: '100%' }}>
            <Form.Item name="count" label="Batch count" style={{ flex: 1 }}>
              <Input type="number" min={1} />
            </Form.Item>
            <Form.Item name="concurrency" label="Concurrency" style={{ flex: 1 }}>
              <Input type="number" min={1} />
            </Form.Item>
          </Space>
          <Space style={{ width: '100%' }}>
            <Form.Item name="register_delay_seconds" label="Delay per registration (seconds)" style={{ flex: 1 }}>
              <InputNumber min={0} precision={1} step={0.5} style={{ width: '100%' }} placeholder="0" />
            </Form.Item>
            <Form.Item name="proxy" label="Proxy (optional)" style={{ flex: 1 }}>
              <Input placeholder="http://user:pass@host:port" />
            </Form.Item>
          </Space>
          <Form.Item name="phone_number" label="Phone number (optional)" extra="To be passed to the platform script if needed">
            <Input placeholder="+1234567890" />
          </Form.Item>
          {platform === 'chatgpt' && (
            <Form.Item label="ChatGPT token mode">
              <ChatGPTRegistrationModeSwitch
                mode={chatgptRegistrationMode}
                onChange={setChatgptRegistrationMode}
              />
            </Form.Item>
          )}
        </Card>

        <Card title="Mailbox Configuration" style={{ marginBottom: 16 }}>
          <Form.Item name="mail_provider" label="Mailbox Service" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'luckmail', label: 'LuckMail' },
                { value: 'mail_import', label: 'Mail import' },
                { value: 'moemail', label: 'MoeMail (sall.cc)' },
                { value: 'tempmail_lol', label: 'TempMail.lol' },
                { value: 'skymail', label: 'SkyMail (CloudMail)' },
                { value: 'cloudmail', label: 'CloudMail (genToken)' },
                { value: 'maliapi', label: 'YYDS Mail / MaliAPI' },
                { value: 'gptmail', label: 'GPTMail' },
                { value: 'opentrashmail', label: 'OpenTrashMail' },
                { value: 'duckmail', label: 'DuckMail' },
                { value: 'freemail', label: 'Freemail' },
                { value: 'laoudo', label: 'Laoudo' },
                { value: 'cfworker', label: 'CF Worker' },
                { value: 'imap_catchall', label: 'IMAP Catchall' },
              ]}
            />
          </Form.Item>
          {mailProviderRaw === 'mail_import' && (
            <Form.Item name="mail_import_source" label="Import Type" rules={[{ required: true }]}>
              <Select
                options={[
                  { value: 'microsoft', label: 'Microsoft mailbox (Outlook / Hotmail)' },
                  { value: 'applemail', label: 'AppleMail / Xiaopingguo' },
                ]}
              />
            </Form.Item>
          )}
          {mailProvider === 'microsoft' && (
            <Form.Item
              name="outlook_backend"
              label="Microsoft receiving method"
              extra="Graph is used by default. If the account has no OAuth credentials, runtime falls back to IMAP automatically."
            >
              <Select
                options={[
                  { value: 'graph', label: 'Graph (default)' },
                  { value: 'imap', label: 'IMAP' },
                ]}
              />
            </Form.Item>
          )}
          {mailProvider === 'skymail' && (
            <>
              <Form.Item name="skymail_api_base" label="API Base">
                <Input placeholder="https://api.skymail.ink" />
              </Form.Item>
              <Form.Item name="skymail_token" label="Authorization Token">
                <Input.Password placeholder="Bearer xxxxx" />
              </Form.Item>
              <Form.Item name="skymail_domain" label="Mailbox domain">
                <Input placeholder="mail.example.com" />
              </Form.Item>
            </>
          )}
          {mailProvider === 'cloudmail' && (
            <>
              <Form.Item name="cloudmail_api_base" label="API base" rules={[{ required: true, message: 'Please enter the CloudMail API address' }]}>
                <Input placeholder="https://cloudmail.example.com" />
              </Form.Item>
              <Form.Item name="cloudmail_admin_email" label="Admin email (optional)" extra="Leave blank to use admin@domain automatically">
                <Input placeholder="admin@example.com" />
              </Form.Item>
              <Form.Item name="cloudmail_admin_password" label="Admin password" rules={[{ required: true, message: 'Please enter the CloudMail admin password' }]}>
                <Input.Password placeholder="admin password" />
              </Form.Item>
              <Form.Item name="cloudmail_domain" label="Mailbox domain (optional)" extra="Supports a single domain or multiple comma-separated domains">
                <Input placeholder="mail.example.com,mail2.example.com" />
              </Form.Item>
              <Form.Item name="cloudmail_subdomain" label="Subdomain (optional)">
                <Input placeholder="pool-a" />
              </Form.Item>
              <Form.Item name="cloudmail_timeout" label="Request timeout (seconds)">
                <InputNumber min={5} max={120} style={{ width: '100%' }} />
              </Form.Item>
            </>
          )}
          {mailProvider === 'laoudo' && (
            <>
              <Form.Item name="laoudo_email" label="Email address">
                <Input placeholder="xxx@laoudo.com" />
              </Form.Item>
              <Form.Item name="laoudo_account_id" label="Account ID">
                <Input placeholder="563" />
              </Form.Item>
              <Form.Item name="laoudo_auth" label="JWT Token">
                <Input placeholder="eyJ..." />
              </Form.Item>
            </>
          )}
          {mailProvider === 'maliapi' && (
            <>
              <Form.Item name="maliapi_base_url" label="API URL">
                <Input placeholder="https://maliapi.215.im/v1" />
              </Form.Item>
              <Form.Item name="maliapi_api_key" label="API Key">
                <Input.Password placeholder="AC-..." />
              </Form.Item>
              <Form.Item name="maliapi_domain" label="Mailbox domain (optional)">
                <Input placeholder="example.com" />
              </Form.Item>
              <Form.Item name="maliapi_auto_domain_strategy" label="Automatic domain strategy">
                <Select
                  options={[
                    { value: 'balanced', label: 'balanced' },
                    { value: 'prefer_owned', label: 'prefer_owned' },
                    { value: 'prefer_public', label: 'prefer_public' },
                  ]}
                />
              </Form.Item>
            </>
          )}
          {mailProvider === 'applemail' && (
            <>
              <Form.Item name="applemail_base_url" label="API URL">
                <Input placeholder="https://www.appleemail.top" />
              </Form.Item>
              <Form.Item
                name="applemail_pool_dir"
                label="Mailbox pool directory"
                extra="Defaults to the mail directory in the project root."
              >
                <Input placeholder="mail" />
              </Form.Item>
              <Form.Item
                name="applemail_pool_file"
                label="Mailbox pool file (optional)"
                extra="Leave blank to automatically use the newest .json/.txt file in the directory. For JSON import, use the global settings page."
              >
                <Input placeholder="applemail_20260403.json" />
              </Form.Item>
              <Form.Item name="applemail_mailboxes" label="Polling folders">
                <Input placeholder="INBOX,Junk" />
              </Form.Item>
            </>
          )}
          {mailProvider === 'gptmail' && (
            <>
              <Form.Item name="gptmail_base_url" label="API URL">
                <Input placeholder="https://mail.chatgpt.org.uk" />
              </Form.Item>
              <Form.Item name="gptmail_api_key" label="API Key">
                <Input.Password placeholder="gpt-test" />
              </Form.Item>
              <Form.Item
                name="gptmail_domain"
                label="Mailbox domain (optional)"
                extra="If you already know an available domain, a random address can be assembled locally to avoid one generate-email request"
              >
                <Input placeholder="example.com" />
              </Form.Item>
            </>
          )}
          {mailProvider === 'opentrashmail' && (
            <>
              <Form.Item name="opentrashmail_api_url" label="API URL" rules={[{ required: true, message: 'Please enter the OpenTrashMail address' }]}>
                <Input placeholder="http://mail.example.com:8085" />
              </Form.Item>
              <Form.Item
                name="opentrashmail_domain"
                label="Mailbox domain (optional)"
                extra="If you already know the currently enabled OpenTrashMail domain, a random address can be assembled locally; leave blank to call /api/random automatically"
              >
                <Input placeholder="xiyoufm.com" />
              </Form.Item>
              <Form.Item
                name="opentrashmail_password"
                label="Site password (optional)"
                extra="Fill this in when OpenTrashMail has PASSWORD protection enabled; it will be appended to the JSON API query parameters automatically"
              >
                <Input.Password placeholder="Leave blank if not enabled" />
              </Form.Item>
            </>
          )}
          {mailProvider === 'cfworker' && (
            <>
              <Form.Item name="cfworker_api_url" label="API URL">
                <Input placeholder="https://apimail.example.com" />
              </Form.Item>
              <Form.Item name="cfworker_admin_token" label="Admin Token">
                <Input placeholder="abc123,,,abc" />
              </Form.Item>
              <Form.Item name="cfworker_custom_auth" label="Site Password">
                <Input.Password placeholder="private site password" />
              </Form.Item>
              <Form.Item
                name="cfworker_domain_override"
                label="Domain override for this task (optional)"
                extra="Leave blank to randomly choose from the enabled domains configured on the settings page."
              >
                <Input placeholder="example.com" />
              </Form.Item>
              <Form.Item
                name="cfworker_subdomain"
                label="Subdomain (optional)"
                extra="When set, xxx@subdomain.root-domain is generated. If random subdomains are enabled, xxx@random-value.subdomain.root-domain is generated instead."
              >
                <Input placeholder="mail / pool-a" />
              </Form.Item>
              <Form.Item name="cfworker_random_subdomain" valuePropName="checked">
                <Checkbox>Generate one random subdomain level before each registration</Checkbox>
              </Form.Item>
              <Form.Item name="cfworker_random_name_subdomain" valuePropName="checked">
                <Checkbox>Use a random name as the subdomain</Checkbox>
              </Form.Item>
              <Form.Item name="cfworker_fingerprint" label="Fingerprint (optional)">
                <Input placeholder="cfb82279f..." />
              </Form.Item>
            </>
          )}
          {mailProvider === 'freemail' && (
            <>
              <Form.Item name="freemail_api_url" label="API URL" rules={[{ required: true, message: 'Please enter the Freemail API address' }]}>
                <Input placeholder="https://mail.example.com" />
              </Form.Item>
              <Form.Item name="freemail_admin_token" label="Admin token (optional)">
                <Input.Password placeholder="JWT_TOKEN" />
              </Form.Item>
              <Form.Item name="freemail_username" label="Username (optional)">
                <Input placeholder="admin" />
              </Form.Item>
              <Form.Item name="freemail_password" label="Password (optional)">
                <Input.Password placeholder="password" />
              </Form.Item>
              <Form.Item name="freemail_domain" label="Mailbox domain (optional)" extra="If provided, this domain will be used first when generating mailboxes">
                <Input placeholder="example.com" />
              </Form.Item>
            </>
          )}
          {mailProvider === 'luckmail' && (
            <>
              <Form.Item name="luckmail_base_url" label="Platform URL">
                <Input placeholder="https://mails.luckyous.com" />
              </Form.Item>
              <Form.Item name="luckmail_api_key" label="API Key">
                <Input.Password placeholder="ak_..." />
              </Form.Item>
              <Form.Item name="luckmail_email_type" label="Mailbox type (optional)">
                <Select
                  options={[
                    { value: '', label: 'Auto / blank' },
                    { value: 'ms_graph', label: 'Microsoft mailbox - Graph' },
                    { value: 'ms_imap', label: 'Microsoft mailbox - IMAP' },
                    { value: 'self_built', label: 'Self-hosted mailbox' },
                  ]}
                />
              </Form.Item>
              <Form.Item name="luckmail_domain" label="Mailbox domain (optional)">
                <Input placeholder="outlook.com" />
              </Form.Item>
            </>
          )}
          {mailProvider === 'imap_catchall' && (
            <>
              <Form.Item name="imap_catchall_server" label="IMAP Server" rules={[{ required: true, message: 'Please enter the IMAP server' }]}>
                <Input placeholder="imap.titan.email" />
              </Form.Item>
              <Form.Item name="imap_catchall_port" label="IMAP Port">
                <Input placeholder="993" />
              </Form.Item>
              <Form.Item name="imap_catchall_username" label="Username (login email)" rules={[{ required: true, message: 'Please enter the IMAP username' }]}>
                <Input placeholder="admin@example.com" />
              </Form.Item>
              <Form.Item name="imap_catchall_password" label="Password" rules={[{ required: true, message: 'Please enter the IMAP password' }]}>
                <Input.Password placeholder="password" />
              </Form.Item>
              <Form.Item name="imap_catchall_domain" label="Catchall domain" rules={[{ required: true, message: 'Please enter the catchall domain' }]}>
                <Input placeholder="example.com" />
              </Form.Item>
              <Form.Item name="imap_catchall_folders" label="Polling folders" extra="Comma-separated list of IMAP folders to poll">
                <Input placeholder="INBOX,Spam" />
              </Form.Item>
            </>
          )}
        </Card>

        {platform === 'chatgpt' && (
          <Card title="ChatGPT Phone Verification" style={{ marginBottom: 16 }}>
            <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
              Only used when the OAuth flow enters `add_phone`, for automatic number acquisition and SMS captcha polling.
            </Text>
            <Form.Item name="smstome_cookie" label="SMSToMe Cookie">
              <Input.Password placeholder="cf_clearance=...; PHPSESSID=..." />
            </Form.Item>
            <Form.Item name="smstome_country_slugs" label="Country list">
              <Input placeholder="united-kingdom,poland,finland" />
            </Form.Item>
            <Form.Item name="smstome_phone_attempts" label="Phone attempt count">
              <Input placeholder="3" />
            </Form.Item>
            <Form.Item name="smstome_otp_timeout_seconds" label="SMS wait time (seconds)">
              <Input placeholder="45" />
            </Form.Item>
            <Form.Item name="smstome_poll_interval_seconds" label="Polling interval (seconds)">
              <Input placeholder="5" />
            </Form.Item>
            <Form.Item name="smstome_sync_max_pages_per_country" label="Sync pages per country">
              <Input placeholder="5" />
            </Form.Item>
          </Card>
        )}

        {captchaSolver === 'yescaptcha' && (
          <Card title="Captcha configuration" style={{ marginBottom: 16 }}>
            <Form.Item name="yescaptcha_key" label="YesCaptcha Key">
              <Input />
            </Form.Item>
          </Card>
        )}

        {captchaSolver === 'local_solver' && (
          <Card title="Local Solver Configuration" style={{ marginBottom: 16 }}>
            <Form.Item name="solver_url" label="Solver URL">
              <Input />
            </Form.Item>
            <Text type="secondary" style={{ fontSize: 12 }}>
              Start command: python services/turnstile_solver/start.py --browser_type camoufox --port 8889
            </Text>
          </Card>
        )}

        <Button type="primary" htmlType="submit" block disabled={polling} icon={polling ? <LoadingOutlined /> : <PlayCircleOutlined />}>
          {polling ? 'Registering...' : 'Start Registration'}
        </Button>
      </Form>

      {task && (
        <Card title={
          <Space>
            <span>Task Status</span>
            <Tag color={
              task.status === 'done' ? 'success' :
              task.status === 'stopped' ? 'warning' :
              task.status === 'failed' ? 'error' : 'processing'
            }>
              {task.status}
            </Tag>
          </Space>
        } style={{ marginTop: 16 }}>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="Task ID">
              <Text copyable style={{ fontFamily: 'monospace' }}>{task.id}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="Progress">{task.progress}</Descriptions.Item>
            <Descriptions.Item label="Skipped">{task.skipped ?? 0}</Descriptions.Item>
          </Descriptions>
          {task.success != null && (
            <div style={{ marginTop: 8, color: '#10b981' }}>
              <CheckCircleOutlined /> Success {task.success}
            </div>
          )}
          {task.errors?.length > 0 && (
            <div style={{ marginTop: 8 }}>
              {task.errors.map((e: string, i: number) => (
                <div key={i} style={{ color: '#ef4444', marginBottom: 4 }}>
                  <CloseCircleOutlined /> {e}
                </div>
              ))}
            </div>
          )}
          {task.error && (
            <div style={{ marginTop: 8, color: '#ef4444' }}>
              <CloseCircleOutlined /> {task.error}
            </div>
          )}
          {task.id ? (
            <div style={{ marginTop: 16 }}>
              <TaskLogPanel taskId={task.id} />
            </div>
          ) : null}
        </Card>
      )}
    </div>
  )
}

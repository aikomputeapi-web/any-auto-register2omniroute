import { Space, Switch, Tag, Typography } from 'antd'

import {
  CHATGPT_REGISTRATION_MODE_ACCESS_TOKEN_ONLY,
  CHATGPT_REGISTRATION_MODE_REFRESH_TOKEN,
  type ChatGPTRegistrationMode,
} from '@/lib/chatgptRegistrationMode'

const { Text } = Typography

type ChatGPTRegistrationModeSwitchProps = {
  mode: ChatGPTRegistrationMode
  onChange: (mode: ChatGPTRegistrationMode) => void
}

export function ChatGPTRegistrationModeSwitch({
  mode,
  onChange,
}: ChatGPTRegistrationModeSwitchProps) {
  const hasRefreshTokenSolution =
    mode === CHATGPT_REGISTRATION_MODE_REFRESH_TOKEN

  return (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      <Space align="center" wrap>
        <Switch
          checked={hasRefreshTokenSolution}
          checkedChildren="With RT"
          unCheckedChildren="Without RT"
          onChange={(checked) =>
            onChange(
              checked
                ? CHATGPT_REGISTRATION_MODE_REFRESH_TOKEN
                : CHATGPT_REGISTRATION_MODE_ACCESS_TOKEN_ONLY,
            )
          }
        />
        <Tag color={hasRefreshTokenSolution ? 'success' : 'default'}>
          {hasRefreshTokenSolution ? 'Recommended' : 'Legacy'}
        </Tag>
      </Space>
      <Text type="secondary">
        {hasRefreshTokenSolution
          ? 'With RT mode uses the new PR pipeline and outputs Access Token + Refresh Token.'
          : 'Without RT mode uses the legacy pipeline and only outputs Access Token / Session. Features depending on RT may not work.'}
      </Text>
    </Space>
  )
}

/**
 * Экран входа — паритет Streamlit-версии login.py.
 *
 * Регистрации нет: учётные записи создаёт администратор, забытый пароль
 * восстанавливается из командной строки. Списка логинов не показываем
 * (перечисление имён ради удобства — дыра в безопасности).
 */

import {
  Alert,
  Button,
  Card,
  Code,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'

import { useAuth } from './authStore'

export function LoginPage() {
  const { status, loginError, loginBusy, login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [touched, setTouched] = useState(false)

  if (status === 'authenticated') return <Navigate to="/" replace />

  const missingFields = touched && (!username.trim() || !password)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setTouched(true)
    if (!username.trim() || !password) return
    const ok = await login(username.trim(), password)
    if (ok) navigate('/', { replace: true })
  }

  return (
    <Stack mih="100vh" align="center" justify="center" gap="sm" p="md">
      <Title order={2}>Вход в boasi_s</Title>
      <Text c="dimmed" size="sm">
        Локальная платформа для научной работы
      </Text>

      <Card withBorder w="100%" maw={400} p="lg">
        <form onSubmit={handleSubmit}>
          <Stack>
            {loginError && (
              <Alert color="red" role="alert">
                {loginError}
              </Alert>
            )}
            {missingFields && (
              <Alert color="yellow" role="alert">
                Заполните оба поля: логин и пароль.
              </Alert>
            )}
            <TextInput
              label="Логин"
              placeholder="имя пользователя"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.currentTarget.value)}
            />
            <PasswordInput
              label="Пароль"
              placeholder="пароль"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.currentTarget.value)}
            />
            <Button type="submit" loading={loginBusy}>
              Войти
            </Button>
          </Stack>
        </form>
      </Card>

      <Text size="sm" c="dimmed">
        Логин и пароль выдаёт администратор. Регистрации нет.
      </Text>
      <Stack gap={4} maw={480}>
        <Text size="xs" c="dimmed">
          Нет доступа?
        </Text>
        <Text size="xs" c="dimmed">
          1. Создать администратора (если система пустая):{' '}
          <Code>./scripts/start.sh admin &lt;логин&gt;</Code>
        </Text>
        <Text size="xs" c="dimmed">
          2. Восстановить пароль: <Code>./scripts/start.sh password &lt;логин&gt;</Code>
        </Text>
        <Text size="xs" c="dimmed">
          3. Посмотреть список пользователей: <Code>./scripts/start.sh users</Code>
        </Text>
      </Stack>
    </Stack>
  )
}

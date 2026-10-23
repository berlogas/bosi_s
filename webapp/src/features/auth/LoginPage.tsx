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

      {/* Команды для администратора живут в docs/ADMIN_GUIDE.md: экран входа
          не должен выглядеть инструкцией для сисадмина. */}
      <Text size="sm" c="dimmed">
        Логин и пароль выдаёт администратор. Регистрации нет — если доступа нет,
        обратитесь к администратору.
      </Text>
    </Stack>
  )
}

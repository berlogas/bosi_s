import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'

import '@mantine/core/styles.css'
import '@mantine/notifications/styles.css'

import { AppProviders } from './app/AppProviders'
import { useAuth, watchSessionExpiry } from './features/auth/authStore'
import { AppRoutes } from './routes'

function App() {
  const bootstrap = useAuth((state) => state.bootstrap)
  const [sessionWatchStarted, setSessionWatchStarted] = useState(false)

  // Восстановление сессии после F5 + подписка на «сессия истекла».
  // StrictMode в dev вызывает эффект дважды — защита флагом.
  useEffect(() => {
    void bootstrap()
    if (!sessionWatchStarted) {
      watchSessionExpiry()
      setSessionWatchStarted(true)
    }
  }, [bootstrap, sessionWatchStarted])

  return <AppRoutes />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppProviders>
      <App />
    </AppProviders>
  </StrictMode>,
)

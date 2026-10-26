/**
 * Единая тема Mantine — семантические токены, радиусы, дефолты компонентов.
 *
 * Цвета: success/warning/error/info — пары light/dark через `virtualColor`:
 * тёмный вариант — своя шкала, где оттенок 0 — тёмный фон под бейдж-«light»,
 * а не белёсая заливка светлой темы. Кастомные поверхности — CSS `light-dark()`
 * в стилях конкретных мест, не в теме.
 *
 * Подключается в AppProviders (MantineProvider theme={theme}).
 */

import { createTheme, virtualColor } from '@mantine/core'
import type { MantineColorsTuple } from '@mantine/core'

// Шкалы для светлой темы: 0 — самая светлая заливка, 9 — самый тёмный текст.
const primaryLight: MantineColorsTuple = [
  '#eef6ff',
  '#d9eaff',
  '#b3d5ff',
  '#8cb0ff',
  '#668cff',
  '#4068ff',
  '#3356cc',
  '#2642a6',
  '#1a3380',
  '#0d2459',
]

const successLight: MantineColorsTuple = [
  '#e8f7ee',
  '#d1efdc',
  '#a3dfb9',
  '#75cf96',
  '#47bf73',
  '#19b050',
  '#169d46',
  '#128a3c',
  '#0f7732',
  '#0b6428',
]

const warningLight: MantineColorsTuple = [
  '#fff8e1',
  '#fff0c2',
  '#ffe184',
  '#ffd246',
  '#ffc308',
  '#ffb400',
  '#e6a200',
  '#cc9000',
  '#b37e00',
  '#996c00',
]

const errorLight: MantineColorsTuple = [
  '#fef0f0',
  '#fde1e1',
  '#fbc3c3',
  '#faa4a4',
  '#f98686',
  '#f86868',
  '#e05d5d',
  '#c85252',
  '#b04747',
  '#993c3c',
]

const infoLight: MantineColorsTuple = [
  '#e8f4fd',
  '#d1e9fb',
  '#a3d3f7',
  '#75bdf3',
  '#47a7ef',
  '#1991eb',
  '#1682d3',
  '#1273bb',
  '#0f64a3',
  '#0b558b',
]

// Шкалы для тёмной темы: 0 — тёмный «бумажный» фон бейджа/алерта, 9 — самая
// яркая заливка/текст. Порядок противоположен светлой шкале.
const primaryDark: MantineColorsTuple = [
  '#0d1526',
  '#10203f',
  '#152a55',
  '#1a3370',
  '#22409b',
  '#2a4fc4',
  '#4a6deb',
  '#6d8bf2',
  '#93aaf7',
  '#bdcffb',
]

const successDark: MantineColorsTuple = [
  '#0c2015',
  '#0f2c1d',
  '#123825',
  '#15442b',
  '#175635',
  '#1a6b41',
  '#1f8a51',
  '#29ab66',
  '#43c782',
  '#7bdca6',
]

const warningDark: MantineColorsTuple = [
  '#261d05',
  '#322607',
  '#3e2f09',
  '#4a380b',
  '#61480e',
  '#7a5a11',
  '#a07715',
  '#c4942c',
  '#ddb25b',
  '#ecd096',
]

const errorDark: MantineColorsTuple = [
  '#2a0d0d',
  '#3a1212',
  '#4a1717',
  '#5c1c1c',
  '#7a2424',
  '#a02e2e',
  '#cc4040',
  '#e56363',
  '#f28f8f',
  '#f8baba',
]

const infoDark: MantineColorsTuple = [
  '#0a1526',
  '#0d1e38',
  '#102745',
  '#133052',
  '#173f6d',
  '#1c5089',
  '#2468ad',
  '#3a86cf',
  '#5fa6e4',
  '#93c8f0',
]

export const theme = createTheme({
  /** Основной бренд */
  primaryColor: 'primary',
  colors: {
    primary: virtualColor({
      name: 'primary',
      light: 'primaryLight',
      dark: 'primaryDark',
    }),
    success: virtualColor({
      name: 'success',
      light: 'successLight',
      dark: 'successDark',
    }),
    warning: virtualColor({
      name: 'warning',
      light: 'warningLight',
      dark: 'warningDark',
    }),
    error: virtualColor({ name: 'error', light: 'errorLight', dark: 'errorDark' }),
    info: virtualColor({ name: 'info', light: 'infoLight', dark: 'infoDark' }),
    // «сырые» шкалы нужны virtualColor как цели ссылок; в цветах их тоже
    // оставляем — нетипизированные пропсы с ними не заводнятся, они скрыты
    // клиентской типизацией MantineColorsTuple
    primaryLight,
    primaryDark,
    successLight,
    successDark,
    warningLight,
    warningDark,
    errorLight,
    errorDark,
    infoLight,
    infoDark,
  },

  /** Радиусы — единый масштаб */
  defaultRadius: 'md',
  radius: {
    xs: '4px',
    sm: '6px',
    md: '8px',
    lg: '12px',
    xl: '16px',
  },

  /** Тени — мягкие, без жёстких границ */
  shadows: {
    xs: '0 1px 2px rgba(0,0,0,0.04)',
    sm: '0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)',
    md: '0 4px 6px rgba(0,0,0,0.05), 0 2px 4px rgba(0,0,0,0.03)',
    lg: '0 10px 15px rgba(0,0,0,0.05), 0 4px 6px rgba(0,0,0,0.03)',
    xl: '0 20px 25px rgba(0,0,0,0.05), 0 10px 10px rgba(0,0,0,0.03)',
  },

  /** Типографика — системный стек, читабельные размеры */
  fontFamily:
    'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  fontFamilyMonospace:
    'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace',
  fontSizes: {
    xs: '12px',
    sm: '13px',
    md: '14px',
    lg: '16px',
    xl: '18px',
  },
  lineHeights: {
    xs: '1.4',
    sm: '1.5',
    md: '1.6',
    lg: '1.6',
    xl: '1.5',
  },

  /** Дефолты вместо пропсов на месте */
  components: {
    Button: {
      defaultProps: {
        size: 'sm',
        radius: 'md',
      },
      styles: {
        root: {
          fontWeight: 500,
        },
      },
    },
    Card: {
      defaultProps: {
        radius: 'md',
        shadow: 'xs',
        withBorder: true,
      },
    },
    Paper: {
      defaultProps: {
        radius: 'md',
        shadow: 'xs',
        withBorder: true,
      },
    },
    Table: {
      defaultProps: {
        highlightOnHover: true,
      },
      styles: {
        th: {
          fontWeight: 600,
          fontSize: '12px',
          textTransform: 'uppercase',
          letterSpacing: '0.02em',
          color: 'var(--mantine-color-dimmed)',
        },
        td: {
          fontSize: '13px',
        },
      },
    },
    Badge: {
      defaultProps: {
        radius: 'sm',
        size: 'sm',
        variant: 'light',
      },
    },
    TextInput: {
      defaultProps: {
        size: 'sm',
        radius: 'md',
      },
    },
    Select: {
      defaultProps: {
        size: 'sm',
        radius: 'md',
      },
    },
    Modal: {
      defaultProps: {
        radius: 'lg',
        centered: true,
      },
    },
    Drawer: {
      defaultProps: {
        size: 'md',
      },
    },
    Alert: {
      defaultProps: {
        radius: 'md',
        withCloseButton: false,
      },
    },
    Progress: {
      defaultProps: {
        size: 'md',
        radius: 'xl',
      },
    },
    Tabs: {
      defaultProps: {
        variant: 'pills',
      },
    },
    SegmentedControl: {
      defaultProps: {
        radius: 'md',
      },
    },
    Tooltip: {
      defaultProps: {
        position: 'top',
        multiline: true,
      },
    },
    Notification: {
      defaultProps: {
        radius: 'md',
        withCloseButton: true,
      },
    },
    AppShell: {
      defaultProps: {
        padding: 'md',
      },
    },
    NavLink: {
      defaultProps: {
        variant: 'light',
        radius: 'md',
      },
    },
    Group: {
      defaultProps: {
        gap: 'sm',
      },
    },
    Stack: {
      defaultProps: {
        gap: 'md',
      },
    },
  },
})

/** Тип для расширения темы в компонентах */
export type AppTheme = typeof theme

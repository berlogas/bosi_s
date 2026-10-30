import '@testing-library/jest-dom/vitest'

// jsdom не реализует matchMedia — Mantine-компоненты зовут его при рендере.
// Десктопное приложение: всегда возвращаем matches=true для десктопных брейкпоинтов
if (!window.matchMedia) {
  window.matchMedia = (query: string): MediaQueryList => {
    const isDesktop = query.includes('min-width: 36em') || query.includes('min-width: 48em') || query.includes('min-width: 62em') || query.includes('min-width: 75em')
    return {
      matches: isDesktop,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    } as MediaQueryList
  }
}

// ResizeObserver нужен AppShell/Mantine-овским хукам.
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  } as unknown as typeof ResizeObserver
}

// jsdom не реализует document.fonts — Mantine Textarea (autosize) слушает
// событие loadingdone на нём и падает без полифилла.
if (!('fonts' in document)) {
  Object.defineProperty(document, 'fonts', {
    value: {
      addEventListener: () => {},
      removeEventListener: () => {},
      ready: Promise.resolve(),
    },
  })
}

// jsdom не реализует scrollIntoView (чат скроллится к свежему сообщению).
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {}
}

// jsdom не реализует EventSource — SSE-подписки на задачи в тестах
// замолкают (реальные события приходят только от сервера).
if (!globalThis.EventSource) {
  globalThis.EventSource = class {
    constructor() {}
    close(): void {}
    addEventListener(): void {}
    removeEventListener(): void {}
    onmessage: ((this: EventSource, ev: MessageEvent) => unknown) | null = null
    onerror: ((this: EventSource, ev: Event) => unknown) | null = null
    onopen: ((this: EventSource, ev: Event) => unknown) | null = null
    readonly CONNECTING = 0
    readonly OPEN = 1
    readonly CLOSED = 2
    readyState = 1
    url = ''
    withCredentials = false
  } as unknown as typeof EventSource
}

// jsdom не реализует requestAnimationFrame — Mantine модальные окна (в т.ч.
// Spotlight) используют его при переключении visible, и без шайма модалка
// остаётся со стилем exiting (opacity: 0) между тестами.
if (!window.requestAnimationFrame) {
  window.requestAnimationFrame = (cb: FrameRequestCallback) =>
    setTimeout(cb, 0) as unknown as number;
}

// react-router-dom useSearchParams не работает в jsdom — мокаем пустыми параметрами.
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useSearchParams: () => [
      new URLSearchParams(),
      () => {},
    ],
  }
})

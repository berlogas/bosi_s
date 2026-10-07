import '@testing-library/jest-dom/vitest'

// jsdom не реализует matchMedia — Mantine-компоненты зовут его при рендере.
if (!window.matchMedia) {
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList
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

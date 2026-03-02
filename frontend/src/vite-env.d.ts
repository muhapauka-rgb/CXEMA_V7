/// <reference types="vite/client" />

interface Window {
  cxemaDesktop?: {
    runUpdate: () => Promise<{ ok: boolean }>
  }
}

export type TelegramThemeParams = Record<string, string | undefined>

type TelegramWebApp = {
  ready: () => void
  expand: () => void
  setHeaderColor?: (color: string) => void
  setBackgroundColor?: (color: string) => void
  themeParams?: TelegramThemeParams
  colorScheme?: "light" | "dark"
  initDataUnsafe?: {
    user?: {
      username?: string
    }
  }
}

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp
    }
  }
}

export function initTelegramWebApp() {
  const webApp = window.Telegram?.WebApp
  if (!webApp) {
    return null
  }

  webApp.ready()
  webApp.expand()

  if (webApp.setHeaderColor) {
    webApp.setHeaderColor("#111827")
  }
  if (webApp.setBackgroundColor) {
    webApp.setBackgroundColor("#0b1220")
  }

  const root = document.documentElement
  const params = webApp.themeParams ?? {}

  if (params.bg_color) {
    root.style.setProperty("--tg-bg-color", params.bg_color)
  }
  if (params.text_color) {
    root.style.setProperty("--tg-text-color", params.text_color)
  }

  root.dataset.colorScheme = webApp.colorScheme ?? "dark"
  return webApp
}

export function getCurrentTelegramUsername() {
  return window.Telegram?.WebApp?.initDataUnsafe?.user?.username?.toLowerCase() ?? null
}

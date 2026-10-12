export type FeedState = 'loading' | 'ready' | 'error'
export type SourceKind = 'local' | 'minio' | 'relay'

export interface SourceHealth {
  tone: 'demo' | 'loading' | 'empty' | 'recent' | 'archive' | 'error'
  label: string
  summary: string
  detail: string
}

const dateFormat = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
})
const relativeFormat = new Intl.RelativeTimeFormat('ru-RU', { numeric: 'auto', style: 'short' })
const dayMs = 24 * 60 * 60 * 1000

function relativeAge(timestamp: number, now: number): string {
  const elapsed = Math.max(0, now - timestamp)
  if (elapsed < 60_000) return 'только что'
  if (elapsed < 60 * 60_000) return relativeFormat.format(-Math.floor(elapsed / 60_000), 'minute')
  if (elapsed < dayMs) return relativeFormat.format(-Math.floor(elapsed / (60 * 60_000)), 'hour')
  return relativeFormat.format(-Math.floor(elapsed / dayMs), 'day')
}

export function describeSourceHealth(input: {
  demo: boolean
  state: FeedState
  source: SourceKind
  fetchedAt: string | null
  newestEventAt: string | null
  now: number
  agentTelemetry?: boolean
}): SourceHealth {
  const { demo, state, source, fetchedAt, newestEventAt, now, agentTelemetry } = input
  if (demo) return {
    tone: 'demo', label: 'Демо', summary: 'Иллюстративные данные',
    detail: 'Показан локальный пример, не события конвейера.',
  }
  const name = source === 'minio' ? 'MinIO' : source === 'relay' ? 'BotParser' : 'Локальный каталог'
  const lastRead = fetchedAt && Number.isFinite(Date.parse(fetchedAt))
    ? ` Последнее успешное чтение: ${dateFormat.format(new Date(fetchedAt))}.` : ''
  if (state === 'error') return {
    tone: 'error', label: 'Нет связи', summary: `${name} · чтение не удалось`,
    detail: `${name} недоступен. ${fetchedAt ? 'Показаны ранее считанные события.' : 'События не загружены.'}${lastRead} Текущий статус задач не подтверждён.`,
  }
  if (state === 'loading') return {
    tone: 'loading', label: 'Чтение', summary: `${name} · ожидание ответа`,
    detail: `Читаю события из источника: ${name}.`,
  }
  const latest = newestEventAt ? Date.parse(newestEventAt) : NaN
  if (!Number.isFinite(latest)) return {
    tone: 'empty', label: 'Пусто', summary: `${name} · событий нет`,
    detail: `Чтение ${name} прошло успешно, но событий пока нет.${lastRead}`,
  }
  const age = relativeAge(latest, now)
  const date = dateFormat.format(new Date(latest))
  const archive = now - latest > dayMs
  return {
    tone: archive ? 'archive' : 'recent',
    label: archive ? 'Архив' : 'События',
    summary: `${name} · ${age}`,
    detail: `Последнее событие: ${date} (${age}).${lastRead} ${agentTelemetry ? 'Статус конкретного запуска определяется heartbeat и завершающим событием.' : 'Текущая активность агентов не подтверждена.'}`,
  }
}

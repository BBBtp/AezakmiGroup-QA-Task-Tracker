import type { Lane, Run, RunRow, RunStateKind, Tone } from './types'
import { formatTime } from './timeline'

export interface AgentRunManifest {
  schemaVersion: 1
  runId: string
  issueKey: string
  correlationId: string | null
  attempt: number
  parentRunId: string | null
  codexThreadId: string | null
  workflowRunId: string | null
  workflowRunAttempt: number | null
  branch: string | null
  baseCommit: string | null
  headCommit: string | null
  stage: string | null
  actor: string | null
  startedAt: string
  lastActionAt: string | null
  lastProcessSignalAt: string | null
  finishedAt: string | null
  eventCount: number
  status: 'queued' | 'running' | 'completed' | 'failed' | 'interrupted' | 'unknown'
  telemetry: 'local' | 'published' | 'publish_failed'
  telemetryError: string | null
  derived?: { rule: string; source: string }
}

export interface AgentEvent {
  schemaVersion: 1
  eventId: string
  runId: string
  issueKey: string
  correlationId: string | null
  attempt: number
  seq: number
  occurredAt: string
  observedAt: string
  source: 'wrapper' | 'codex-exec'
  sourceType: string | null
  codexVersion: string | null
  kind: string
  actor: string | null
  itemId: string | null
  parentItemId: string | null
  status: string | null
  detail: Record<string, unknown>
}

export interface AgentFeed {
  source: 'local' | 'minio' | 'relay'
  fetchedAt: string
  runs: AgentRunManifest[]
}

const statusLabels: Record<AgentRunManifest['status'], string> = {
  queued: 'В очереди', running: 'Выполняется', completed: 'Завершён',
  failed: 'Ошибка', interrupted: 'Прерван', unknown: 'Сигнал устарел',
}

function runState(status: AgentRunManifest['status']): RunStateKind {
  return status === 'running' ? 'active' : status === 'completed' ? 'completed'
    : status === 'failed' ? 'failed' : status === 'unknown' || status === 'interrupted' ? 'blocked' : 'waiting'
}

function toneFor(event: AgentEvent): Tone {
  return event.status === 'failed' || /failed|error|parse_error|interrupted/.test(event.kind) ? 'red'
    : event.status === 'declined' ? 'amber' : event.kind === 'process.heartbeat' ? 'muted' : 'green'
}

function labelFor(event: AgentEvent): string {
  const labels: Record<string, string> = {
    'run.started': 'Запуск Codex', 'run.finished': 'Codex завершил работу',
    'process.heartbeat': 'Сигнал процесса', 'stream.parse_error': 'Ошибка потока событий',
    'thread.started': 'Поток Codex открыт', 'turn.started': 'Ход начат',
    'turn.completed': 'Ход завершён', 'turn.failed': 'Ошибка хода',
    'turn.interrupted': 'Ход прерван', 'codex.error': 'Ошибка Codex',
    'source.unknown': 'Неизвестное событие источника',
  }
  if (labels[event.kind]) return labels[event.kind]
  const [kind, phase] = event.kind.split('.')
  if (kind === 'agent_message') return `Сообщение агента ${phase === 'started' ? 'начато' : phase === 'updated' ? 'обновлено' : 'завершено'}`
  const subjects: Record<string, string> = {
    command: 'Команда', file: 'Изменение файлов', mcp: 'MCP вызов', web: 'Поиск в сети',
    agent_message: 'Сообщение агента', plan: 'План', item: 'Действие',
  }
  const verbs: Record<string, string> = kind === 'mcp' || kind === 'item' || kind === 'web'
    ? { started: 'начался', updated: 'обновлён', completed: 'завершён' }
    : { started: 'началась', updated: 'обновлена', completed: 'завершена' }
  const subject = subjects[kind] ?? 'Событие'
  return `${subject} ${verbs[phase] ?? ''}`.trim()
}

function eventFacts(event: AgentEvent): [string, string][] {
  const facts: [string, string][] = [
    ['Последовательность', String(event.seq)], ['Тип', event.kind],
    ['Источник', event.source], ['Время наблюдения', formatTime(event.observedAt)],
  ]
  if (event.itemId) facts.push(['Item ID', event.itemId])
  if (event.parentItemId) facts.push(['Parent item ID', event.parentItemId])
  for (const [name, key] of [
    ['Команда', 'label'], ['Инструмент', 'tool'], ['Сервер', 'server'],
    ['Причина', 'reason'], ['Код завершения', 'exitCode'], ['Длительность, мс', 'durationMs'],
  ] as const) {
    const value = event.detail[key]
    if (typeof value === 'string' || typeof value === 'number') facts.push([name, String(value)])
  }
  return facts
}

export function projectAgentRun(manifest: AgentRunManifest, events: AgentEvent[], source: AgentFeed['source'], hasMore = false): Run {
  const sourceLabel = source === 'minio' ? 'Codex · MinIO' : source === 'relay' ? 'Codex · BotParser' : 'Codex · локальный каталог'
  const sorted = [...events].sort((a, b) => a.seq - b.seq)
  const observed = [sorted.at(-1)?.observedAt, manifest.lastActionAt, manifest.lastProcessSignalAt, manifest.finishedAt, manifest.startedAt]
    .filter((value): value is string => Boolean(value))
    .sort((a, b) => Date.parse(b) - Date.parse(a))[0]
  const end = manifest.finishedAt ?? manifest.lastProcessSignalAt ?? observed
  const stateKind = runState(manifest.status)
  const lane: Lane = manifest.stage === 'verification' || manifest.stage === 'runner' ? 'check'
    : manifest.stage === 'analysis' || manifest.stage === 'design' ? 'design' : 'implementation'
  const actorId = 'actor'
  const rows: RunRow[] = [
    {
      id: 'run', parentId: null, kind: 'group', label: `Запуск ${manifest.issueKey}`,
      detail: `попытка ${manifest.attempt}`, status: statusLabels[manifest.status],
      recordType: 'Agent run v1', summary: `Управляемый запуск Codex. ${manifest.eventCount} событий в источнике.`,
      source: sourceLabel, time: formatTime(manifest.startedAt), ref: manifest.runId,
      span: manifest.finishedAt ? { startAt: manifest.startedAt, endAt: manifest.finishedAt, tone: stateKind === 'completed' ? 'green' : 'red' } : undefined,
      facts: [
        ['Run ID', manifest.runId], ['Задача', manifest.issueKey], ['Попытка', String(manifest.attempt)],
        ['Событий', String(manifest.eventCount)], ['Ветка', manifest.branch ?? 'не указана'],
        ['Публикация', manifest.telemetry],
      ],
      payload: manifest as unknown as Record<string, unknown>,
      needsAttention: stateKind === 'blocked' || stateKind === 'failed',
    },
    {
      id: actorId, parentId: 'run', kind: 'group', label: manifest.actor ?? 'Codex',
      detail: manifest.stage ?? 'агент', status: statusLabels[manifest.status],
      summary: 'События этого исполнителя записаны обёрткой Codex CLI.', source: sourceLabel,
      time: formatTime(observed), ref: manifest.codexThreadId ?? manifest.runId,
      facts: [
        ['Роль', manifest.actor ?? 'не указана'], ['Этап', manifest.stage ?? 'не указан'],
        ['Thread ID', manifest.codexThreadId ?? 'не получен'],
        ['Последнее действие', manifest.lastActionAt ? formatTime(manifest.lastActionAt) : 'нет'],
        ['Последний сигнал процесса', manifest.lastProcessSignalAt ? formatTime(manifest.lastProcessSignalAt) : 'нет'],
      ],
    },
  ]
  let currentTurn = ''
  let turnIndex = 0
  const started = new Map<string, AgentEvent>()
  for (const event of sorted) {
    if (event.kind === 'turn.started') {
      turnIndex++
      currentTurn = `turn-${turnIndex}`
      rows.push({
        id: currentTurn, parentId: actorId, kind: 'group', label: `Ход ${turnIndex}`,
        detail: formatTime(event.observedAt), status: 'Выполняется',
        summary: 'Ход Codex CLI; длительность подтверждается завершающим событием.',
        source: sourceLabel, time: formatTime(event.observedAt), ref: event.eventId,
        observedAt: event.observedAt, pointTone: 'muted',
      })
    }
    const label = labelFor(event)
    const tone = toneFor(event)
    const first = event.itemId && event.kind.endsWith('.completed') ? started.get(event.itemId) : undefined
    const row: RunRow = {
      id: event.eventId, parentId: currentTurn || actorId,
      kind: tone === 'red' ? 'gate' : 'event', label,
      detail: typeof event.detail.label === 'string' ? event.detail.label : formatTime(event.observedAt),
      status: event.status === 'failed' ? 'Ошибка' : event.status === 'in_progress' ? 'Выполняется' : 'Зафиксировано',
      recordType: 'Agent action v1', summary: `${label}. Содержимое сообщений, вывод команд и текст файлов в трассу не включены.`,
      source: sourceLabel, time: formatTime(event.observedAt), observedAt: event.observedAt,
      pointTone: tone, ref: event.eventId, facts: eventFacts(event),
      payload: event as unknown as Record<string, unknown>, needsAttention: tone === 'red' || tone === 'amber',
      ...(first ? { span: { startAt: first.observedAt, endAt: event.observedAt, tone } } : {}),
    }
    rows.push(row)
    if (event.itemId && event.kind.endsWith('.started')) started.set(event.itemId, event)
    if (/^turn\.(completed|failed|interrupted)$/.test(event.kind) && currentTurn) {
      const turn = rows.find((item) => item.id === currentTurn)!
      turn.status = event.status === 'failed' ? 'Ошибка' : 'Завершён'
      turn.span = { startAt: turn.observedAt ?? event.observedAt, endAt: event.observedAt, tone }
      currentTurn = ''
    }
  }
  if (hasMore) rows.push({
    id: 'more', parentId: 'run', kind: 'pending', label: 'Есть следующие события', detail: '',
    status: 'Загрузите следующую страницу', summary: 'Источник содержит дополнительные события.',
    source: sourceLabel, time: '',
  })
  const lastEvent = sorted.at(-1)
  const signal = manifest.status === 'unknown' ? 'сигнал процесса устарел' : manifest.status === 'running'
    ? 'heartbeat менее 60 секунд назад' : 'запуск завершён'
  const axisEnd = Math.max(Date.parse(end), Date.parse(manifest.startedAt) + 60_000)
  return {
    id: manifest.runId, issueKey: manifest.issueKey,
    title: `${manifest.issueKey} · ${manifest.actor ?? 'Codex'}`,
    state: statusLabels[manifest.status], stateKind,
    subtitle: `Codex trace · ${manifest.runId} · попытка ${manifest.attempt}`,
    startedAt: manifest.startedAt, lastObservedAt: observed, axisEndAt: new Date(axisEnd).toISOString(),
    signal, defaultRowId: lastEvent?.eventId ?? 'run', lane,
    reason: manifest.status === 'unknown' ? 'Последний heartbeat старше 60 секунд' : statusLabels[manifest.status],
    nextStep: manifest.status === 'unknown' ? 'Проверить процесс и источник событий' :
      manifest.status === 'failed' || manifest.status === 'interrupted' ? 'Открыть завершающее событие' : 'Изучить трассу',
    recentEvent: lastEvent ? labelFor(lastEvent) : statusLabels[manifest.status],
    recentSource: sourceLabel, recentTime: observed, rows,
  }
}

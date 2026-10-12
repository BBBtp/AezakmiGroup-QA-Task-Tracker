import { formatTime } from './timeline'
import { countLabel } from './format'
import type { Lane, Run, RunRow, RunStateKind, Tone } from './types'

export interface FactoryEvent {
  schemaVersion: 1
  eventId: string
  occurredAt: string
  correlationId: string
  type: 'intake_evaluated' | 'draft_pr_created' | 'verification_completed' | 'stale_source_detected'
  stage: 'intake' | 'engineer' | 'runner'
  outcome: 'ready' | 'needs_information' | 'not_automatable' | 'created' | 'passed' | 'failed' | 'blocked' | 'stale'
  issueKey: string
  requirementId: number | null
  caseId: number | null
  fingerprint: string
  metrics: Record<string, number | boolean>
  failureCategories: Record<string, number>
  links: { pullRequest: string | null; githubRun: string | null; report: string | null }
}

export interface FactoryFeed {
  source: 'local' | 'minio'
  fetchedAt: string
  events: FactoryEvent[]
  readinessByEventId?: Record<string, { source: 'analysis.json v3'; blockers: { code: string; source: 'tracker' | 'doqa' | 'coverage' }[] }>
}

const blockerLabels: Record<string, string> = {
  'missing-summary': 'Нет заголовка задачи',
  'missing-description': 'Нет описания задачи',
  'missing-acceptance-criteria': 'Нет критериев приёмки',
  'missing-ready-tag': 'Нет отметки готовности',
  'needs-requirement': 'Нужно связанное требование',
  'requirement-key-mismatch': 'Ключ требования не совпадает',
  'requirement-link-needs-confirmation': 'Связь с требованием требует подтверждения',
  'requirement-needs-actualization': 'Требование требует актуализации',
  'existing-autotest-linked': 'Уже привязан автотест',
  'case-match-ambiguous': 'Найдено несколько подходящих тест-кейсов',
  'case-match-needs-confirmation': 'Тест-кейс требует подтверждения',
  'confirmed-case-not-found': 'Подтверждённый тест-кейс не найден',
  'existing-coverage-needs-review': 'Существующее покрытие требует проверки',
  'needs-case': 'Нет подтверждённого DoQA case',
  'case-not-planned': 'Тест-кейс не запланирован для автоматизации',
}

function readinessFor(event: FactoryEvent, feed: FactoryFeed) {
  return feed.readinessByEventId?.[event.eventId]
}

function readinessReasons(event: FactoryEvent, feed: FactoryFeed) {
  return readinessFor(event, feed)?.blockers.map(({ code }) => blockerLabels[code] ?? code) ?? []
}

const stageLabels = { intake: 'Intake', engineer: 'Разработка', runner: 'Проверка' }
const eventLabels = {
  intake_evaluated: 'Входные данные оценены',
  draft_pr_created: 'Draft PR создан',
  verification_completed: 'Проверка завершена',
  stale_source_detected: 'Источник изменился',
}
const outcomeLabels = {
  ready: 'Готово к следующему этапу',
  needs_information: 'Нужны сведения',
  not_automatable: 'Автоматизация не подходит',
  created: 'Создано',
  passed: 'Проверка пройдена',
  failed: 'Проверка не пройдена',
  blocked: 'Заблокировано',
  stale: 'Источник устарел',
}

function stateFor(event: FactoryEvent): { kind: RunStateKind; state: string; reason: string; next: string; lane: Lane; tone: Tone } {
  if (event.outcome === 'failed') return { kind: 'failed', state: 'Проверка не пройдена', reason: 'Проверка завершилась ошибкой', next: 'Открыть GitHub Run и классифицировать ошибку', lane: 'check', tone: 'red' }
  if (event.outcome === 'blocked' || event.outcome === 'stale') return { kind: 'blocked', state: outcomeLabels[event.outcome], reason: event.outcome === 'stale' ? 'Fingerprint источника изменился' : 'Проверка заблокирована', next: 'Изучить событие и источник', lane: 'check', tone: 'amber' }
  if (event.outcome === 'needs_information' || event.outcome === 'not_automatable') return { kind: 'blocked', state: outcomeLabels[event.outcome], reason: outcomeLabels[event.outcome], next: 'Проверить входные требования', lane: 'design', tone: 'amber' }
  if (event.type === 'verification_completed') return { kind: 'completed', state: outcomeLabels[event.outcome], reason: 'Верификация завершена', next: 'Открыть результаты проверки', lane: 'check', tone: 'green' }
  if (event.type === 'draft_pr_created') return { kind: 'waiting', state: 'Draft PR создан', reason: 'Ожидается независимый review', next: 'Проверить Draft PR', lane: 'implementation', tone: 'muted' }
  return { kind: 'waiting', state: 'Intake готов', reason: 'Входные данные готовы', next: 'Проверить переход к реализации', lane: 'design', tone: 'muted' }
}

function rowFor(event: FactoryEvent, feed: FactoryFeed): RunRow {
  const state = stateFor(event)
  const label = eventLabels[event.type]
  const time = formatTime(event.occurredAt)
  const facts: [string, string][] = [
    ['Этап', stageLabels[event.stage]],
    ['Результат', outcomeLabels[event.outcome]],
    ['Время события', time],
    ['Correlation ID', event.correlationId],
    ['Case ID', event.caseId === null ? 'не указан' : String(event.caseId)],
  ]
  const reasons = readinessReasons(event, feed)
  if (reasons.length) {
    facts.push(['Причины', 'Локальный analysis.json v3; задача, fingerprint и результат сверены с событием'])
    reasons.forEach((reason, index) => facts.push([`Причина ${index + 1}`, reason]))
  }
  if (event.type === 'intake_evaluated') {
    if (typeof event.metrics.acceptanceCriteria === 'number') facts.push(['Критериев', String(event.metrics.acceptanceCriteria)])
    if (typeof event.metrics.coveredCriteria === 'number') facts.push(['Покрыто критериев', String(event.metrics.coveredCriteria)])
  }
  if (event.type === 'verification_completed') {
    for (const key of ['total', 'passed', 'failed', 'broken', 'skipped'] as const) {
      if (typeof event.metrics[key] === 'number') facts.push([{ total: 'Всего', passed: 'Успешно', failed: 'Неуспешно', broken: 'Сломано', skipped: 'Пропущено' }[key], String(event.metrics[key])])
    }
  }
  const links = ([
    ['Draft PR', event.links.pullRequest],
    ['GitHub Run', event.links.githubRun],
    ['Отчёт', event.links.report],
  ] as const).flatMap(([label, url]) => url ? [{ label, url }] : [])
  return {
    id: event.eventId,
    parentId: `stage-${event.stage}`,
    kind: event.outcome === 'blocked' || event.outcome === 'stale' || event.outcome === 'needs_information' || event.outcome === 'not_automatable' ? 'gate' : 'event',
    label,
    detail: time,
    status: outcomeLabels[event.outcome],
    recordType: 'Factory event v1',
    summary: `${label}. Результат: ${outcomeLabels[event.outcome].toLowerCase()}.${reasons.length ? ` Причины по локальному analysis.json: ${reasons.join('; ')}.` : ''} Это запись конвейера; действия между такими событиями здесь не наблюдаются.`,
    source: feed.source === 'minio' ? 'Factory events · MinIO' : 'Factory events · локальный каталог',
    time,
    observedAt: event.occurredAt,
    pointTone: state.tone,
    ref: event.eventId,
    facts,
    links,
    payload: event as unknown as Record<string, unknown>,
    needsAttention: state.kind === 'blocked' || state.kind === 'failed',
  }
}

export function projectFactoryRuns(feed: FactoryFeed): Run[] {
  const grouped = new Map<string, FactoryEvent[]>()
  for (const event of feed.events) {
    const group = grouped.get(event.correlationId) ?? []
    group.push(event)
    grouped.set(event.correlationId, group)
  }
  return [...grouped].map(([correlationId, sourceEvents]) => {
    const events = sourceEvents.sort((a, b) => Date.parse(a.occurredAt) - Date.parse(b.occurredAt) || a.eventId.localeCompare(b.eventId))
    const first = events[0]
    const last = events.at(-1)!
    const state = stateFor(last)
    const reasons = readinessReasons(last, feed)
    const source = feed.source === 'minio' ? 'MinIO' : 'локальный каталог'
    const rows: RunRow[] = [{
      id: 'run', parentId: null, kind: 'group', label: `Запуск ${first.issueKey}`,
      detail: `${events.length} ${countLabel(events.length, 'событие', 'события', 'событий')}`, status: state.state,
      summary: `Корреляция ${correlationId}. Зафиксировано ${events.length} ${countLabel(events.length, 'событие', 'события', 'событий')} конвейера; промежуточная активность не выводится из пауз между ними.`,
      source: `Factory events · ${source}`, time: `${formatTime(first.occurredAt)} — ${formatTime(last.occurredAt)}`,
      ref: correlationId, facts: [['Задача', first.issueKey], ['Событий', String(events.length)], ['Последнее событие', formatTime(last.occurredAt)]],
    }]
    const stages = (['intake', 'engineer', 'runner'] as const)
      .filter((stage) => events.some((event) => event.stage === stage))
      .sort((a, b) => Date.parse(events.find((event) => event.stage === a)!.occurredAt) - Date.parse(events.find((event) => event.stage === b)!.occurredAt))
    for (const stage of stages) {
      const stageEvents = events.filter((event) => event.stage === stage)
      if (!stageEvents.length) continue
      rows.push({
        id: `stage-${stage}`, parentId: 'run', kind: 'group', label: stageLabels[stage],
        detail: `${stageEvents.length} ${countLabel(stageEvents.length, 'событие', 'события', 'событий')}`, status: `Зафиксировано: ${stageEvents.length}`,
        summary: `Для этапа ${stageLabels[stage]} зафиксировано ${stageEvents.length} ${countLabel(stageEvents.length, 'событие', 'события', 'событий')}. Длительность исполнения и работа агента между ними не подтверждены.`,
        source: `Factory events · ${source}`, time: formatTime(stageEvents.at(-1)!.occurredAt),
        ref: `${correlationId}-${stage}`,
      })
      rows.push(...stageEvents.map((event) => rowFor(event, feed)))
    }
    const axisStart = Date.parse(first.occurredAt)
    const axisEnd = Math.max(Date.parse(last.occurredAt), axisStart + 60_000)
    return {
      id: correlationId,
      issueKey: first.issueKey,
      title: first.caseId ? `${first.issueKey} · TC-${first.caseId}` : first.issueKey,
      state: state.state,
      stateKind: state.kind,
      subtitle: `События конвейера · ${correlationId}`,
      startedAt: first.occurredAt,
      lastObservedAt: last.occurredAt,
      axisEndAt: new Date(axisEnd).toISOString(),
      signal: 'событие зафиксировано',
      defaultRowId: last.eventId,
      lane: state.lane,
      reason: reasons.length ? reasons.join(' · ') : state.reason,
      nextStep: reasons.length ? 'Проверить блокирующие данные в источниках' : state.next,
      recentEvent: eventLabels[last.type],
      recentSource: `Factory events · ${source}`,
      recentTime: last.occurredAt,
      rows,
    }
  }).sort((a, b) => Date.parse(b.lastObservedAt) - Date.parse(a.lastObservedAt) || a.id!.localeCompare(b.id!))
}

import { Fragment, useState } from 'react'
import type { ReactNode } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import type { Run, RunRow } from '../data/types'

export type DetailTab = 'overview' | 'events' | 'source'

const typeLabel: Record<RunRow['kind'], string> = {
  group: 'РОЛЬ / ЗАПУСК', event: 'СОБЫТИЕ', gate: 'УСЛОВИЕ ПЕРЕДАЧИ', pending: 'ОЖИДАЕТ',
}

function stateTone(row: RunRow): string {
  if (row.pointTone === 'red') return 'red'
  if (row.pointTone === 'amber') return ''
  if (row.pointTone === 'green') return 'green'
  if (row.pointTone === 'muted') return 'blue'
  if (/ошиб|не пройден/i.test(row.status)) return 'red'
  if (/останов|устарел|неизвестен|нужны сведения|не подходит|заблокирован/i.test(row.status)) return ''
  if (/ожидает|нет подтверждения/i.test(row.status)) return 'blue'
  return 'green'
}

function evidenceType(row: RunRow): string {
  if (row.recordType) return row.recordType
  return { group: 'Сводка событий', event: 'Запись события', gate: 'Вывод по условию', pending: 'Нет подтверждённого события' }[row.kind]
}

function JsonPayload({ payload, live, agent }: { payload: Record<string, unknown>; live: boolean; agent: boolean }) {
  const json = JSON.stringify(payload, null, 2)
  const tokens: ReactNode[] = []
  const pattern = /"(?:\\.|[^"\\])*"(?=\s*:)|"(?:\\.|[^"\\])*"|\b(?:true|false|null|\d+)\b/g
  let last = 0
  for (const match of json.matchAll(pattern)) {
    const index = match.index ?? 0
    if (index > last) tokens.push(json.slice(last, index))
    const token = match[0]
    const after = json.slice(index + token.length).trimStart()
    const kind = token.startsWith('"') ? (after.startsWith(':') ? 'key' : 'value') : 'missing'
    tokens.push(<span className={kind} key={index}>{token}</span>)
    last = index + token.length
  }
  if (last < json.length) tokens.push(json.slice(last))
  return <div className="evidence"><div className="evidence-header"><span>{agent ? 'Очищенная трасса Codex' : live ? 'Событие конвейера' : 'Локальный снимок'}</span><span>{agent ? 'agentActionEvent v1' : live ? 'event v1' : 'mock JSON'}</span></div><pre>{tokens}</pre></div>
}

function EventTimeline({ row }: { row: RunRow }) {
  const entries = row.events ?? [[row.label, row.time]]
  return <><div className="section-title">Ход событий</div><div className="mini-timeline">
    {entries.map(([label, time], index) => <div className={`mini-event ${index === entries.length - 1 && row.needsAttention ? row.pointTone === 'red' ? 'failed' : 'blocked' : ''}`} key={`${label}-${index}`}>
      <span className="pin" /><span className="event-main">{label}</span><time>{time}</time>
    </div>)}
  </div></>
}

function Facts({ facts }: { facts: [string, string][] }) {
  return <dl className="fact-list">{facts.map(([name, value]) => <Fragment key={name}><dt>{name}</dt><dd>{value}</dd></Fragment>)}</dl>
}

function EvidenceLinks({ row }: { row: RunRow }) {
  if (!row.links?.length) return null
  return <><div className="section-title">Ссылки на подтверждения</div><div className="evidence-links">{row.links.map(({ label, url }) => <a href={url} target="_blank" rel="noopener noreferrer" key={label}>{label} ↗</a>)}</div></>
}

function PanelContent({ run, row, tab }: { run: Run; row: RunRow; tab: DetailTab }) {
  const live = Boolean(run.id)
  const agent = run.subtitle.startsWith('Codex trace')
  if (tab === 'events') return <><EventTimeline row={row} /><p className="note">{agent ? 'Показаны очищенные события управляемого запуска Codex. Heartbeat подтверждает процесс, но не действие агента.' : live ? 'Показаны только подтверждённые события конвейера. Паузы между ними не описывают работу агента.' : 'Времена и события взяты из иллюстративного локального снимка.'}</p></>
  if (tab === 'source') return <>
    <div className="section-title">Происхождение записи</div>
    <Facts facts={[
      ['Тип записи', evidenceType(row)], ['Источник', row.source], ['Время', row.time],
      ['ID записи', row.ref ?? `${run.issueKey.toLowerCase()}-${row.id}`], ['Достоверность', agent ? 'Очищенное событие Codex CLI v1' : live ? 'Событие конвейера v1' : 'Иллюстративные данные'],
    ]} />
    {row.payload && <JsonPayload payload={row.payload} live={live} agent={agent} />}
    <EvidenceLinks row={row} />
    <p className="note">{live ? 'Событие прочитано без изменений; доступ к источнику только на чтение.' : 'Это структура макета, не подтверждённый API-контракт.'}</p>
  </>
  const title = row.kind === 'pending' ? 'Что известно' : row.recordType === 'Условие передачи' ? 'Условие и доказательства' : row.kind === 'gate' ? 'Факты и доказательства' : 'Подтверждение'
  return <>
    <div className={`state-line ${stateTone(row)}`}><span className="dot" />{row.status}</div>
    <p className="detail-summary">{row.summary}</p>
    <EventTimeline row={row} />
    <div className="section-title">{title}</div>
    <Facts facts={row.facts ?? [['Источник', row.source], ['Время', row.time]]} />
    <EvidenceLinks row={row} />
    {row.payload && <JsonPayload payload={row.payload} live={live} agent={agent} />}
    <p className="note">{live ? 'Действия в Tracker, DoQA, CI и MinIO из этого экрана не выполняются.' : 'Внешние системы не подключены. Операторские действия здесь не исполняются.'}</p>
  </>
}

interface DetailPanelProps { run: Run; row?: RunRow; tab: DetailTab; onTab: (tab: DetailTab) => void }

export function DetailPanel({ run, row, tab, onTab }: DetailPanelProps) {
  const reducedMotion = useReducedMotion()
  const [copyState, setCopyState] = useState<{ reference: string; label: string } | null>(null)
  const reference = row ? row.ref ?? `${run.issueKey.toLowerCase()}-${row.id}` : ''
  const copyLabel = copyState?.reference === reference ? copyState.label : 'Скопировать ID записи'

  async function copyReference() {
    if (!row) return
    try {
      await navigator.clipboard.writeText(reference)
      setCopyState({ reference, label: 'ID скопирован' })
    } catch {
      setCopyState({ reference, label: `Не удалось скопировать · ${reference}` })
    }
  }

  return <aside className="detail" aria-label="Подробности выбранного события">
    <div className="detail-head">
      <div className="detail-kicker">{row ? row.recordType?.toUpperCase() ?? typeLabel[row.kind] : 'ПОИСК'}</div>
      <h2 className="detail-title">{row?.label ?? 'Нет совпадений'}</h2>
      <div className="tabs" role="tablist" aria-label="Данные события">
        {([['overview', 'Обзор'], ['events', 'События'], ['source', 'Источник']] as const).map(([value, label]) => <button
          className={`tab ${tab === value ? 'active' : ''}`}
          id={`tab-${value}`}
          type="button"
          role="tab"
          aria-controls="detail-body"
          aria-selected={tab === value}
          disabled={!row}
          key={value}
          onClick={() => onTab(value)}
        >{label}</button>)}
      </div>
    </div>
    <div className="detail-body" id="detail-body" role="tabpanel" aria-labelledby={`tab-${tab}`} aria-live="polite">
      {row ? <AnimatePresence initial={false}>
        <motion.div key={`${run.issueKey}:${row.id}:${tab}`} initial={{ opacity: reducedMotion ? 1 : 0.7 }} animate={{ opacity: 1 }} exit={{ opacity: reducedMotion ? 1 : 0.7 }} transition={{ duration: reducedMotion ? 0 : 0.12 }}>
          <PanelContent run={run} row={row} tab={tab} />
        </motion.div>
      </AnimatePresence> : <p className="detail-summary">Измените поиск или отключите фильтр проблем, чтобы снова увидеть события запуска.</p>}
    </div>
    <div className="detail-actions"><button type="button" onClick={copyReference} disabled={!row}>{copyLabel}</button></div>
  </aside>
}

import type { CSSProperties, KeyboardEvent } from 'react'
import { ChevronDown, Clock3, Info, PlaySquare, Search, ShieldAlert, UserRound } from 'lucide-react'
import { axisTicks, depth, formatTime, interval, position, seconds } from '../data/timeline'
import type { Run, RunRow } from '../data/types'

interface InspectorProps {
  run: Run
  rows: RunRow[]
  selectedId: string | undefined
  archiveNotice: string | null
  query: string
  onQuery: (query: string) => void
  problemsOnly: boolean
  onProblemsOnly: () => void
  collapsed: ReadonlySet<string>
  onExpandAll: () => void
  onCollapseAll: () => void
  onSelect: (id: string, toggleIfCurrent?: boolean) => void
  hasMore?: boolean
  traceLoading?: boolean
  traceError?: string | null
  onLoadMore?: () => void
}

function durationLabel(startAt: string, endAt: string) {
  const duration = Math.max(0, seconds(endAt) - seconds(startAt))
  if (duration >= 86400) return `${Math.floor(duration / 86400)}d`
  if (duration >= 3600) return `${Math.floor(duration / 3600)}h`
  return duration >= 60 ? `${Math.floor(duration / 60)}m` : `${Math.max(1, Math.round(duration))}s`
}

function rowIcon(row: RunRow) {
  if (row.kind === 'gate') return { name: 'gate', Icon: ShieldAlert }
  if (row.kind === 'event') return { name: 'event', Icon: Info }
  if (row.kind === 'pending') return { name: 'pending', Icon: Clock3 }
  if (row.parentId) return { name: 'role', Icon: UserRound }
  return { name: 'run', Icon: PlaySquare }
}

export function Inspector({ run, rows, selectedId, archiveNotice, query, onQuery, problemsOnly, onProblemsOnly, collapsed, onExpandAll, onCollapseAll, onSelect, hasMore, traceLoading, traceError, onLoadMore }: InspectorProps) {
  function clearFilters() {
    onQuery('')
    if (problemsOnly) onProblemsOnly()
  }

  function handleKeys(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    if (!rows.length) return
    event.preventDefault()
    const current = rows.findIndex((row) => row.id === selectedId)
    const next = rows[Math.max(0, Math.min(rows.length - 1, current + (event.key === 'ArrowDown' ? 1 : -1)))]
    if (next) {
      onSelect(next.id)
      requestAnimationFrame(() => {
        const element = document.querySelector<HTMLButtonElement>(`[data-row="${next.id}"]`)
        element?.focus()
        element?.scrollIntoView({ block: 'nearest' })
      })
    }
  }

  return <main className="main">
    <div className="run-head">
      <div className="run-eyebrow"><span className="run-key">{run.issueKey}</span><span className={`run-state ${run.stateKind}`}>{run.state}{archiveNotice && <span className="state-as-of"> · на момент записи</span>}</span></div>
      <h1 className="run-title">{run.title}</h1>
      <p className="run-subtitle">{run.subtitle}</p>
      <div className="run-meta"><span>Первое событие <b>{formatTime(run.startedAt)}</b></span><span>Последнее событие <b>{formatTime(run.lastObservedAt)}</b></span><span>Наблюдение <b>{run.signal}</b></span></div>
      {archiveNotice && <p className="feed-warning" role="status">{archiveNotice}</p>}
    </div>
    <div className="tools">
      <label className="search"><Search className="ui-icon" aria-hidden="true" strokeWidth={1.7} /><input type="search" value={query} onChange={(event) => onQuery(event.target.value)} placeholder="Найти в трассе" aria-label="Найти в трассе" /></label>
      <span className="toolbar-spacer" />
      <button className={`toolbutton ${problemsOnly ? 'active' : ''}`} type="button" aria-pressed={problemsOnly} onClick={onProblemsOnly}>Только проблемы</button>
      <button className="toolbutton" type="button" onClick={onExpandAll}>Развернуть все</button>
      <button className="toolbutton" type="button" onClick={onCollapseAll}>Свернуть</button>
      {hasMore && <button className="toolbutton" type="button" onClick={onLoadMore} disabled={traceLoading}>{traceLoading ? 'Загружаю…' : 'Ещё события'}</button>}
    </div>
    {traceError && <p className="feed-warning" role="alert">{traceError}</p>}
    <div className="trace-scroll" onKeyDown={handleKeys}>
      <div className="trace">
        <div className="trace-heading"><div className="trace-label-head">Роль, событие или условие</div><div className="axis">{axisTicks(run).map((tick, index) => <span key={index}>{tick}</span>)}</div></div>
        <div>{rows.length ? rows.map((row) => {
          const level = depth(row, run.rows)
          const hasChildren = run.rows.some((candidate) => candidate.parentId === row.id)
          const { name, Icon } = rowIcon(row)
          const bar = row.span ? interval(run, row.span) : null
          const barStyle = bar ? { '--start': `${bar.left}%`, '--width': `${bar.width}%` } as CSSProperties : undefined
          const pointStyle = row.observedAt ? { '--start': `${position(run, row.observedAt)}%` } as CSSProperties : undefined
          return <button
            className={`trace-row ${row.kind} ${row.pointTone ? `tone-${row.pointTone}` : ''} ${bar || row.observedAt ? 'has-time' : ''} ${row.id === selectedId ? 'selected' : ''}`}
            type="button"
            key={row.id}
            data-row={row.id}
            aria-pressed={row.id === selectedId}
            aria-expanded={hasChildren && !query.trim() && !problemsOnly ? !collapsed.has(row.id) : undefined}
            onClick={() => onSelect(row.id, true)}
          >
            <span className="label-cell">
              <span className="indent" style={{ '--indent': `${level * 18}px` } as CSSProperties} aria-hidden="true" />
              <span className={`chevron ${hasChildren ? '' : 'empty'} ${collapsed.has(row.id) ? 'is-collapsed' : ''}`} aria-hidden="true"><ChevronDown className="ui-icon" strokeWidth={1.7} /></span>
              <span className={`node-icon ${name}`} aria-hidden="true"><Icon className="ui-icon" strokeWidth={1.7} /></span>
              <span className="node-text">{row.label}</span><span className="node-detail">{row.detail}</span>
            </span>
            <span className="time-cell" aria-hidden="true">
              {bar && row.span && <><span className={`bar ${row.span.tone === 'green' ? '' : row.span.tone}`} style={barStyle} /><span className={`bar-label ${row.span.tone === 'muted' ? 'muted' : ''}`} style={{ '--start': `${bar.left}%` } as CSSProperties}>{durationLabel(row.span.startAt, row.span.endAt)}</span></>}
              {row.observedAt && <span className={`mark ${row.pointTone ?? 'muted'}`} style={pointStyle} />}
              <span className="endline" style={{ left: `${position(run, run.lastObservedAt)}%` }} />
            </span>
          </button>
        }) : <div className="trace-row empty-search"><span>{query.trim() ? 'По запросу событий не найдено' : 'Проблемных событий в этом запуске нет'}</span><button type="button" onClick={clearFilters}>Показать всю трассу</button></div>}</div>
      </div>
    </div>
  </main>
}

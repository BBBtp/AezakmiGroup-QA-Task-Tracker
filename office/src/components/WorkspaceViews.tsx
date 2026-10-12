import { useState } from 'react'
import { ChevronDown, ClipboardList, Code2, Columns3, FlaskConical, LayoutDashboard, Workflow } from 'lucide-react'
import { groupRunsByIssue, needsAttention, runKey } from '../data/issue-groups'
import { countLabel } from '../data/format'
import { formatTime, seconds } from '../data/timeline'
import type { Lane, Run } from '../data/types'

export type View = 'dashboard' | 'board' | 'runs'
export type QueueFilter = 'all' | 'attention' | 'other'

const lanes: { id: Lane; label: string; icon: typeof ClipboardList }[] = [
  { id: 'design', label: 'Дизайн тестов', icon: ClipboardList },
  { id: 'implementation', label: 'Реализация', icon: Code2 },
  { id: 'check', label: 'Проверка', icon: FlaskConical },
]

interface SidebarProps {
  runs: Run[]
  sourceLabel: string
  archive: boolean
  view: View
  onView: (view: View) => void
  activeKey: string
  onOpenRun: (key: string) => void
  query: string
  onQuery: (query: string) => void
  filter: QueueFilter
  onFilter: (filter: QueueFilter) => void
}

export function Sidebar({ runs, sourceLabel, archive, view, onView, activeKey, onOpenRun, query, onQuery, filter, onFilter }: SidebarProps) {
  const [expandedIssues, setExpandedIssues] = useState<Set<string>>(() => new Set())
  const normalized = query.trim().toLocaleLowerCase('ru')
  const shown = groupRunsByIssue(runs).flatMap((group) => {
    if (filter === 'attention' && !needsAttention(group.latest)) return []
    if (filter === 'other' && needsAttention(group.latest)) return []
    const matches = normalized
      ? group.runs.filter((run) => `${run.issueKey} ${run.title} ${run.state} ${run.id ?? ''}`.toLocaleLowerCase('ru').includes(normalized))
      : group.runs
    return matches.length ? [{ ...group, matches }] : []
  })
  function toggleIssue(issueKey: string) {
    setExpandedIssues((previous) => {
      const next = new Set(previous)
      if (next.has(issueKey)) next.delete(issueKey)
      else next.add(issueKey)
      return next
    })
  }
  const items: { view: View; label: string; icon: typeof LayoutDashboard }[] = [
    { view: 'dashboard', label: 'Дашборд', icon: LayoutDashboard },
    { view: 'board', label: 'Доска', icon: Columns3 },
    { view: 'runs', label: 'Запуски', icon: Workflow },
  ]

  return <aside className="rail">
    <nav className="rail-nav" aria-label="Разделы">
      {items.map(({ view: itemView, label, icon: Icon }) => <button
        className={`navitem ${view === itemView ? 'active' : ''}`}
        type="button"
        key={itemView}
        onClick={() => onView(itemView)}
        aria-current={view === itemView ? 'page' : undefined}
      ><Icon className="ui-icon" aria-hidden="true" strokeWidth={1.7} />{label}{itemView === 'runs' && <span className="count">{runs.length}</span>}</button>)}
    </nav>
    <div className="queue-head"><strong>{archive ? 'История задач' : 'Задачи'}</strong><span>{shown.length}</span></div>
    <div className="queue-controls">
      <input className="queue-search" type="search" value={query} onChange={(event) => onQuery(event.target.value)} placeholder="Найти задачу" aria-label="Найти задачу" />
      <div className="queue-filters" role="group" aria-label="Фильтр запусков">
        {([['all', 'Все'], ['attention', 'Внимание'], ['other', 'Остальные']] as const).map(([value, label]) => <button
          className={`queue-filter ${filter === value ? 'active' : ''}`}
          type="button"
          key={value}
          aria-pressed={filter === value}
          onClick={() => onFilter(value)}
        >{label}</button>)}
      </div>
    </div>
    <div className="case-list">
      {shown.length ? shown.map((group) => {
        const selectedHere = view === 'runs' && group.runs.some((run) => runKey(run) === activeKey)
        const selectedOlder = selectedHere && runKey(group.latest) !== activeKey
        const expanded = normalized.length > 0 || expandedIssues.has(group.issueKey)
        return <div className={`issue-group ${selectedHere ? 'has-selection' : ''}`} key={group.issueKey}>
          <div className="issue-header">
            <button className={`issue-main ${selectedHere && !selectedOlder ? 'active' : ''}`} type="button" onClick={() => onOpenRun(runKey(group.latest))} aria-current={selectedHere && !selectedOlder ? 'page' : undefined}>
              <span className="issue-top"><span className="case-key">{group.issueKey}</span><span className={`case-state ${group.latest.stateKind}`} aria-hidden="true" /></span>
              <span className="issue-status">{group.latest.state}</span>
              <span className="issue-meta">{group.runs.length} {countLabel(group.runs.length, 'запуск', 'запуска', 'запусков')} · {formatTime(group.latest.lastObservedAt)}</span>
            </button>
            {group.runs.length > 1 && <button className={`issue-toggle ${expanded ? 'expanded' : ''}`} type="button" aria-label={`${expanded ? 'Скрыть' : 'Показать'} историю ${group.issueKey}`} aria-expanded={expanded} aria-controls={`history-${group.issueKey}`} onClick={() => toggleIssue(group.issueKey)}><ChevronDown className="ui-icon" aria-hidden="true" /></button>}
          </div>
          {expanded && <div className="issue-history" id={`history-${group.issueKey}`} aria-label={`История ${group.issueKey}`}>
            {group.matches.map((run) => <button className={`history-run ${selectedHere && runKey(run) === activeKey ? 'active' : ''}`} key={runKey(run)} type="button" onClick={() => { setExpandedIssues((previous) => new Set(previous).add(group.issueKey)); onOpenRun(runKey(run)) }} aria-current={selectedHere && runKey(run) === activeKey ? 'page' : undefined}>
              <span className="history-date">{formatTime(run.lastObservedAt)}</span><span className="history-title">{run.title}</span><span className="history-state">{run.state}</span>
            </button>)}
          </div>}
        </div>
      }) : <div className="queue-empty"><span>Задач по фильтру нет</span><button type="button" onClick={() => { onQuery(''); onFilter('all') }}>Сбросить фильтры</button></div>}
    </div>
    <div className="rail-footer"><strong>Источник событий</strong>{sourceLabel}</div>
  </aside>
}

interface WorkspaceProps { runs: Run[]; sourceLabel: string; archiveNotice: string | null; onOpenRun: (key: string) => void }

export function Dashboard({ runs, sourceLabel, archiveNotice, onOpenRun }: WorkspaceProps) {
  const latest = groupRunsByIssue(runs).map((group) => group.latest)
  const priority = latest.filter(needsAttention)
  const signals = latest.filter((run) => !needsAttention(run)).slice(0, 6)
  const recent = [...runs].sort((a, b) => seconds(b.recentTime) - seconds(a.recentTime)).slice(0, 20)
  return <section className="workspace-view" id="dashboard-view" aria-labelledby="dashboard-title">
    <div className="view-head"><div><h1 id="dashboard-title">{archiveNotice ? 'Архив событий' : 'Операционная сводка'}</h1><p>Последний записанный запуск по каждой задаче.</p></div><div className="view-meta"><strong>{latest.length}</strong> {countLabel(latest.length, 'задача', 'задачи', 'задач')} &nbsp; / &nbsp; <strong>{runs.length}</strong> {countLabel(runs.length, 'запуск', 'запуска', 'запусков')}</div></div>
    {archiveNotice && <p className="feed-warning" role="status">{archiveNotice}</p>}
    <div className="dashboard-grid">
      <div><div className="view-section-head">{archiveNotice ? 'Блокировки на момент записи' : 'Нужны сведения по последней записи'} <span>{priority.length} {countLabel(priority.length, 'задача', 'задачи', 'задач')}</span></div><div className="priority-list">
        {priority.map((run) => <button className="priority-row" type="button" key={run.id ?? run.issueKey} onClick={() => onOpenRun(run.id ?? run.issueKey)}>
          <span className="priority-key"><span className={`case-state ${run.stateKind}`} aria-hidden="true" />{run.issueKey}</span><span className="priority-main"><strong>{run.reason}</strong><small>{run.title}</small></span><span className="priority-next"><em>{archiveNotice ? 'Предлагалось проверить' : 'Следующая проверка'}</em>{run.nextStep}</span>
        </button>)}
        {!priority.length && <p className="overview-note">Таких событий нет.</p>}
      </div></div>
      <div><div className="view-section-head">Другие события <span>последние записи</span></div><div className="signal-list">
        {signals.map((run) => <button className="signal-row" type="button" key={run.id ?? run.issueKey} onClick={() => onOpenRun(run.id ?? run.issueKey)}>
          <span className="signal-key">{run.issueKey}</span><span className="signal-main"><strong className={`status-chip ${run.stateKind}`}>{run.state}</strong><small>{run.reason} · {formatTime(run.recentTime)}</small></span>
        </button>)}
      </div></div>
    </div>
    <div className="view-section-head recent-heading">Последние события <span>по времени</span></div>
    <div className="recent-list">{recent.map((run) => <button className="recent-row" type="button" key={run.id ?? run.issueKey} onClick={() => onOpenRun(run.id ?? run.issueKey)}><time>{formatTime(run.recentTime)}</time><span className="recent-key">{run.issueKey}</span><span className="recent-text">{run.recentEvent}</span><span className="recent-source">{run.recentSource}</span></button>)}</div>
    <p className="overview-note">Источник: {sourceLabel}. Дашборд показывает последнюю запись по каждой задаче; история запусков доступна в разделе «Запуски».</p>
  </section>
}

export function Board({ runs, archiveNotice, onOpenRun }: WorkspaceProps) {
  const latest = groupRunsByIssue(runs).map((group) => group.latest)
  return <section className="workspace-view" id="board-view" aria-labelledby="board-title">
    <div className="view-head"><div><h1 id="board-title">Доска передач</h1><p>Этап последнего записанного запуска по каждой задаче.</p></div><div className="view-meta"><strong>{latest.length}</strong> {countLabel(latest.length, 'задача', 'задачи', 'задач')} &nbsp; / &nbsp; <strong>{lanes.length}</strong> {countLabel(lanes.length, 'этап', 'этапа', 'этапов')}</div></div>
    {archiveNotice && <p className="feed-warning" role="status">{archiveNotice}</p>}
    <div className="board-layout">{lanes.map((lane) => {
      const entries = latest.filter((run) => run.lane === lane.id)
      const LaneIcon = lane.icon
      return <section className="board-lane" data-lane={lane.id} key={lane.id}>
        <div className="board-lane-head"><strong><LaneIcon className="ui-icon" aria-hidden="true" strokeWidth={1.7} />{lane.label}</strong><span>{entries.length}</span></div>
        <div className="board-items">{entries.map((run) => <button className="board-card" type="button" key={run.id ?? run.issueKey} onClick={() => onOpenRun(run.id ?? run.issueKey)}>
          <span className="board-card-top"><span className="board-card-key">{run.issueKey}</span><span className={`status-chip ${run.stateKind}`}>{run.state}</span></span>
          <span className="board-card-title">{run.title}</span><span className="board-card-reason">{run.reason}</span><span className="board-card-next">{archiveNotice ? 'План на момент записи: ' : 'Далее: '}{run.nextStep}</span>
          <span className="board-card-bottom"><span>{run.recentSource}</span><span>{formatTime(run.recentTime)}</span></span>
        </button>)}</div>
      </section>
    })}</div>
    <p className="board-note">Клик по задаче открывает её запуск. Доска отображает снимок и не меняет внешние статусы.</p>
  </section>
}

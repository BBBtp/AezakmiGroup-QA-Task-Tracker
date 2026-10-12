import { useEffect, useMemo, useState } from 'react'
import { Workflow } from 'lucide-react'
import { Board, Dashboard, Sidebar } from './components/WorkspaceViews'
import type { QueueFilter, View } from './components/WorkspaceViews'
import { Inspector } from './components/Inspector'
import { DetailPanel } from './components/DetailPanel'
import type { DetailTab } from './components/DetailPanel'
import { mockRuns } from './data/mock-runs'
import { groupRunsByIssue, needsAttention } from './data/issue-groups'
import { projectFactoryRuns } from './data/factory-runs'
import type { FactoryFeed } from './data/factory-runs'
import { projectAgentRun } from './data/agent-runs'
import type { AgentEvent, AgentFeed, AgentRunManifest } from './data/agent-runs'
import { describeSourceHealth } from './data/source-health'
import type { FeedState } from './data/source-health'
import { formatTime, visibleRows } from './data/timeline'
import type { Run } from './data/types'

const queryParams = new URLSearchParams(window.location.search)
const demoMode = queryParams.get('demo') === '1'
type SourceChoice = 'minio' | 'agent-minio' | 'agent-relay'
const initialSource: SourceChoice = queryParams.get('source') === 'agent-minio' ? 'agent-minio'
  : queryParams.get('source') === 'minio' ? 'minio' : 'agent-relay'
const isAgentSource = (source: SourceChoice) => source.startsWith('agent-')

function App() {
  const [factoryRuns, setFactoryRuns] = useState<Run[]>([])
  const [agentManifests, setAgentManifests] = useState<AgentRunManifest[]>([])
  const [agentPages, setAgentPages] = useState<Record<string, { events: AgentEvent[]; nextSeq: number; hasMore: boolean }>>({})
  const [traceLoading, setTraceLoading] = useState(false)
  const [traceError, setTraceError] = useState<string | null>(null)
  const [feedState, setFeedState] = useState<FeedState>('loading')
  const [feedSource, setFeedSource] = useState<SourceChoice>(initialSource)
  const [fetchedAt, setFetchedAt] = useState<string | null>(null)
  const [feedError, setFeedError] = useState<string | null>(null)
  const [view, setView] = useState<View>('runs')
  const [activeKey, setActiveKey] = useState(demoMode ? 'FRONT-174' : '')
  const [selectedId, setSelectedId] = useState('doqa')
  const [tab, setTab] = useState<DetailTab>('overview')
  const [queueQuery, setQueueQuery] = useState('')
  const [queueFilter, setQueueFilter] = useState<QueueFilter>('all')
  const [traceQuery, setTraceQuery] = useState('')
  const [problemsOnly, setProblemsOnly] = useState(false)
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set())

  useEffect(() => {
    if (demoMode) return
    let cancelled = false
    async function load() {
      try {
        const source = feedSource === 'agent-relay' ? 'relay' : 'minio'
        const response = await fetch(`${isAgentSource(feedSource) ? '/api/agent-runs' : '/api/factory-events'}?source=${source}`, { cache: 'no-store' })
        const data = await response.json()
        if (cancelled) return
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`)
        if (data.source !== source) throw new Error('Источник ответа не совпадает с выбранным')
        if (isAgentSource(feedSource)) {
          const feed = data as AgentFeed
          setAgentManifests(feed.runs)
          setFetchedAt(feed.fetchedAt)
        } else {
          const feed = data as FactoryFeed
          setFactoryRuns(projectFactoryRuns(feed))
          setFetchedAt(feed.fetchedAt)
        }
        setFeedError(null)
        setFeedState('ready')
      } catch (error) {
        if (cancelled) return
        setFeedError(error instanceof Error ? error.message : 'Не удалось прочитать события')
        setFeedState('error')
      }
    }
    void load()
    const timer = window.setInterval(() => { void load() }, 30_000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [feedSource])

  const runs = demoMode ? mockRuns : isAgentSource(feedSource)
    ? agentManifests.map((manifest) => projectAgentRun(manifest, agentPages[manifest.runId]?.events ?? [], feedSource === 'agent-relay' ? 'relay' : 'minio', agentPages[manifest.runId]?.hasMore ?? manifest.eventCount > 0))
    : factoryRuns
  const run = runs.find((candidate) => (candidate.id ?? candidate.issueKey) === activeKey) ?? runs[0]
  useEffect(() => {
    if (demoMode || !isAgentSource(feedSource) || !run?.id) return
    let cancelled = false
    const manifest = agentManifests.find((candidate) => candidate.runId === run.id)
    if (!manifest) return
    const previousPage = agentPages[run.id]
    if (previousPage && (previousPage.hasMore || previousPage.events.length >= manifest.eventCount)) return
    const source = feedSource === 'agent-relay' ? 'relay' : 'minio'
    async function loadTrace() {
      setTraceLoading(true)
      setTraceError(null)
      try {
        const response = await fetch(`/api/agent-runs/${manifest!.issueKey}/${manifest!.runId}/events?source=${source}&after=${previousPage?.nextSeq ?? 0}`, { cache: 'no-store' })
        const page = await response.json()
        if (!response.ok) throw new Error(page.error || `HTTP ${response.status}`)
        if (!cancelled) setAgentPages((previous) => ({ ...previous, [manifest!.runId]: {
          events: [...(previous[manifest!.runId]?.events ?? []), ...page.events],
          nextSeq: page.nextSeq, hasMore: page.hasMore,
        } }))
      } catch (error) {
        if (!cancelled) setTraceError(error instanceof Error ? error.message : 'Трасса недоступна')
      } finally {
        if (!cancelled) setTraceLoading(false)
      }
    }
    void loadTrace()
    return () => { cancelled = true }
  }, [feedSource, run?.id, agentManifests, agentPages])
  const rows = useMemo(() => run ? visibleRows(run, collapsed, traceQuery, problemsOnly) : [], [run, collapsed, traceQuery, problemsOnly])
  const selectedRow = rows.find((row) => row.id === selectedId) ?? rows.find((row) => row.id === run?.defaultRowId) ?? rows.at(-1)
  const sourceLabel = demoMode ? 'Иллюстративные данные' : isAgentSource(feedSource)
    ? feedSource === 'agent-relay' ? 'Codex trace · BotParser' : 'Codex trace · MinIO'
    : 'Factory events · MinIO'
  const newestEventAt = runs.reduce<string | null>((latest, candidate) => !latest || Date.parse(candidate.lastObservedAt) > Date.parse(latest) ? candidate.lastObservedAt : latest, null)
  const sourceHealth = describeSourceHealth({ demo: demoMode, state: feedState, source: feedSource === 'agent-relay' ? 'relay' : 'minio', fetchedAt, newestEventAt, now: Date.now(), agentTelemetry: isAgentSource(feedSource) })
  const lastEventDate = newestEventAt && Number.isFinite(Date.parse(newestEventAt))
    ? new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(newestEventAt))
    : null
  const archiveNotice = sourceHealth.tone === 'archive' && lastEventDate
    ? `Архив событий. Последний сигнал — ${lastEventDate}. Текущий статус задач и активность агентов не подтверждены.`
    : sourceHealth.tone === 'error' && lastEventDate
      ? `Источник сейчас недоступен. Показаны ранее считанные события; последняя запись — ${lastEventDate}. Текущий статус задач не подтверждён.`
      : null

  function changeSource(source: SourceChoice) {
    if (source === feedSource) return
    setFactoryRuns([])
    setAgentManifests([])
    setAgentPages({})
    setTraceError(null)
    setFeedState('loading')
    setFetchedAt(null)
    setFeedError(null)
    setFeedSource(source)
    setActiveKey('')
    setView('runs')
    const url = new URL(window.location.href)
    url.searchParams.set('source', source)
    window.history.replaceState(null, '', url)
  }

  function openRun(key: string) {
    const next = runs.find((candidate) => (candidate.id ?? candidate.issueKey) === key)
    if (!next) return
    const issueLatest = groupRunsByIssue(runs).find((group) => group.issueKey === next.issueKey)?.latest ?? next
    const matchesFilter = queueFilter === 'all' || (queueFilter === 'attention' ? needsAttention(issueLatest) : !needsAttention(issueLatest))
    const matchesQuery = `${next.issueKey} ${next.title} ${next.state}`.toLocaleLowerCase('ru').includes(queueQuery.trim().toLocaleLowerCase('ru'))
    if (!matchesFilter || !matchesQuery) { setQueueFilter('all'); setQueueQuery('') }
    setActiveKey(key)
    setSelectedId(next.defaultRowId)
    setTab('overview')
    setTraceQuery('')
    setProblemsOnly(false)
    setCollapsed(new Set())
    setView('runs')
  }

  function selectRow(id: string, toggleIfCurrent = false) {
    if (toggleIfCurrent && selectedRow?.id === id && !traceQuery.trim() && !problemsOnly && run?.rows.some((row) => row.parentId === id)) {
      setCollapsed((previous) => { const next = new Set(previous); if (next.has(id)) next.delete(id); else next.add(id); return next })
    }
    setSelectedId(id)
    setTab('overview')
  }

  function collapseAll() {
    if (run) setCollapsed(new Set(run.rows.filter((row) => run.rows.some((candidate) => candidate.parentId === row.id)).map((row) => row.id)))
  }

  async function loadMore() {
    if (!run?.id || !isAgentSource(feedSource)) return
    const manifest = agentManifests.find((candidate) => candidate.runId === run.id)
    const previous = agentPages[run.id]
    if (!manifest || !previous?.hasMore || traceLoading) return
    setTraceLoading(true)
    setTraceError(null)
    try {
      const source = feedSource === 'agent-relay' ? 'relay' : 'minio'
      const response = await fetch(`/api/agent-runs/${manifest.issueKey}/${manifest.runId}/events?source=${source}&after=${previous.nextSeq}`, { cache: 'no-store' })
      const page = await response.json()
      if (!response.ok) throw new Error(page.error || `HTTP ${response.status}`)
      setAgentPages((current) => ({ ...current, [manifest.runId]: {
        events: [...(current[manifest.runId]?.events ?? []), ...page.events],
        nextSeq: page.nextSeq, hasMore: page.hasMore,
      } }))
    } catch (error) {
      setTraceError(error instanceof Error ? error.message : 'Следующая страница недоступна')
    } finally { setTraceLoading(false) }
  }

  const breadcrumb = view === 'runs' ? run?.issueKey ?? 'Запуски' : view === 'dashboard' ? 'Дашборд' : 'Доска'

  return <div className={`app mode-${view} state-${run?.stateKind ?? 'empty'} ${run ? '' : 'empty-feed'}`}>
    <div className="brandbar"><span className="brandmark"><Workflow className="ui-icon" aria-hidden="true" strokeWidth={1.6} /></span><span className="brandname">Agent Office</span><span className="workspace-name">Mini App</span></div>
    <header className="topbar">
      <span className="crumb">Рабочее пространство</span><span className="slash">/</span><span className="crumb current">{breadcrumb}</span>
      <select className="mobile-view" value={view} onChange={(event) => setView(event.target.value as View)} aria-label="Выбрать раздел"><option value="dashboard">Дашборд</option><option value="board">Доска</option><option value="runs">Запуски</option></select>
      <select className="mobile-case" value={run?.id ?? run?.issueKey ?? ''} onChange={(event) => openRun(event.target.value)} aria-label="Выбрать запуск">{groupRunsByIssue(runs).map((group) => <optgroup label={group.issueKey} key={group.issueKey}>{group.runs.map((item) => <option key={item.id ?? item.issueKey} value={item.id ?? item.issueKey}>{item.title} · {formatTime(item.lastObservedAt)}</option>)}</optgroup>)}</select>
      <div className="top-right">{!demoMode && <select className="source-select" aria-label="Источник событий" value={feedSource} onChange={(event) => changeSource(event.target.value as SourceChoice)}><option value="agent-relay">Codex · BotParser</option><option value="minio">Фабрика · MinIO</option><option value="agent-minio">Codex · MinIO</option></select>}<div className={`source-health ${sourceHealth.tone}`} role="status" aria-label={sourceHealth.detail} title={sourceHealth.detail}><span className="source-health-dot" aria-hidden="true" /><strong>{sourceHealth.label}</strong><span>{sourceHealth.summary}</span></div></div>
    </header>
    <Sidebar runs={runs} sourceLabel={sourceLabel} archive={Boolean(archiveNotice)} view={view} onView={setView} activeKey={run?.id ?? run?.issueKey ?? ''} onOpenRun={openRun} query={queueQuery} onQuery={setQueueQuery} filter={queueFilter} onFilter={setQueueFilter} />
    {run ? <><Inspector run={run} rows={rows} selectedId={selectedRow?.id} archiveNotice={archiveNotice} query={traceQuery} onQuery={setTraceQuery} problemsOnly={problemsOnly} onProblemsOnly={() => setProblemsOnly((value) => !value)} collapsed={collapsed} onExpandAll={() => setCollapsed(new Set())} onCollapseAll={collapseAll} onSelect={selectRow} hasMore={isAgentSource(feedSource) && Boolean(agentPages[run.id ?? '']?.hasMore)} traceLoading={traceLoading} traceError={traceError} onLoadMore={() => { void loadMore() }} /><DetailPanel run={run} row={selectedRow} tab={tab} onTab={setTab} /></> : <main className="main feed-empty"><h1>{feedState === 'loading' ? 'Читаю события' : feedState === 'error' ? 'Источник недоступен' : 'Событий пока нет'}</h1><p>{feedState === 'error' ? feedError : feedState === 'ready' ? `В источнике ${sourceLabel} нет событий.` : 'Данные появятся после загрузки подтверждённых событий.'}</p><div className="empty-actions"><a href="/office/?demo=1">Открыть иллюстративный прототип</a></div></main>}
    {run && <Dashboard runs={runs} sourceLabel={sourceLabel} archiveNotice={archiveNotice} onOpenRun={openRun} />}
    {run && <Board runs={runs} sourceLabel={sourceLabel} archiveNotice={archiveNotice} onOpenRun={openRun} />}
    <footer className="statusbar"><span>{view === 'runs' ? <><kbd>↑</kbd> <kbd>↓</kbd> Выбрать событие</> : 'Выберите запуск, чтобы открыть трассу'}</span>{view === 'runs' && <span><kbd>Enter</kbd> Развернуть этап</span>}<span className="right"><span className={`signal ${sourceHealth.tone}`}>●</span> {demoMode ? 'Демо · моки' : feedState === 'error' ? `${sourceLabel} · ошибка чтения${fetchedAt ? ` · успешно считано ${formatTime(fetchedAt)}` : ''}` : fetchedAt ? `${sourceLabel} · считано ${formatTime(fetchedAt)}` : 'Ожидание чтения'}</span></footer>
  </div>
}

export default App

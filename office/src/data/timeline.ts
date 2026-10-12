import type { Run, RunRow } from './types'

export function seconds(time: string): number {
  if (time.includes('T')) return Date.parse(time) / 1000
  const [hours = 0, minutes = 0, secs = 0] = time.split(':').map(Number)
  return hours * 3600 + minutes * 60 + secs
}

export function formatTime(time: string): string {
  if (!time.includes('T')) return time
  return new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(time))
}

export function position(run: Run, time: string): number {
  const start = seconds(run.startedAt)
  const duration = seconds(run.axisEndAt) - start
  if (duration <= 0) return 0
  return Math.max(0, Math.min(100, ((seconds(time) - start) / duration) * 100))
}

export function interval(run: Run, span: NonNullable<RunRow['span']>): { left: number; width: number } {
  const left = position(run, span.startAt)
  return { left, width: Math.max(0.4, position(run, span.endAt) - left) }
}

export function axisTicks(run: Run): string[] {
  const start = seconds(run.startedAt)
  const duration = seconds(run.axisEndAt) - start
  return Array.from({ length: 5 }, (_, index) => {
    const total = start + (duration * index) / 4
    if (run.startedAt.includes('T')) {
      const options: Intl.DateTimeFormatOptions = duration >= 86400
        ? { day: '2-digit', month: 'short' }
        : { hour: '2-digit', minute: '2-digit' }
      return new Intl.DateTimeFormat('ru-RU', options).format(new Date(total * 1000))
    }
    const hour = Math.floor(total / 3600)
    const minute = Math.floor((total % 3600) / 60)
    return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
  })
}

export function depth(row: RunRow, rows: RunRow[]): number {
  let level = 0
  let parentId = row.parentId
  while (parentId) {
    level += 1
    parentId = rows.find((candidate) => candidate.id === parentId)?.parentId ?? null
  }
  return level
}

export function visibleRows(run: Run, collapsed: ReadonlySet<string>, query: string, problemsOnly: boolean): RunRow[] {
  const normalized = query.trim().toLocaleLowerCase('ru')
  if (normalized || problemsOnly) {
    const included = new Set<string>()
    for (const row of run.rows) {
      if (problemsOnly && !row.needsAttention) continue
      if (normalized && !`${row.label} ${row.detail} ${row.status} ${row.summary}`.toLocaleLowerCase('ru').includes(normalized)) continue
      let current: RunRow | undefined = row
      while (current) {
        included.add(current.id)
        current = run.rows.find((candidate) => candidate.id === current?.parentId)
      }
    }
    return run.rows.filter((row) => included.has(row.id))
  }
  return run.rows.filter((row) => {
    let parentId = row.parentId
    while (parentId) {
      if (collapsed.has(parentId)) return false
      parentId = run.rows.find((candidate) => candidate.id === parentId)?.parentId ?? null
    }
    return true
  })
}

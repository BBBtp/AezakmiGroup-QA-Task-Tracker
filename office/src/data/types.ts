export type RunStateKind = 'blocked' | 'failed' | 'active' | 'waiting' | 'completed'
export type RowKind = 'group' | 'event' | 'gate' | 'pending'
export type Tone = 'green' | 'amber' | 'red' | 'muted'
export type Lane = 'design' | 'implementation' | 'check'

export interface RunRow {
  id: string
  parentId: string | null
  kind: RowKind
  label: string
  detail: string
  status: string
  recordType?: string
  summary: string
  source: string
  time: string
  span?: { startAt: string; endAt: string; tone: Tone }
  observedAt?: string
  pointTone?: Tone
  ref?: string
  events?: [string, string][]
  facts?: [string, string][]
  links?: { label: string; url: string }[]
  payload?: Record<string, unknown>
  needsAttention?: boolean
}

export interface Run {
  id?: string
  issueKey: string
  title: string
  state: string
  stateKind: RunStateKind
  subtitle: string
  startedAt: string
  lastObservedAt: string
  axisEndAt: string
  signal: string
  defaultRowId: string
  lane: Lane
  reason: string
  nextStep: string
  recentEvent: string
  recentSource: string
  recentTime: string
  rows: RunRow[]
}

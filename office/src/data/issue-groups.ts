import { seconds } from './timeline'
import type { Run } from './types'

export interface IssueGroup {
  issueKey: string
  latest: Run
  runs: Run[]
}

export function runKey(run: Run): string {
  return run.id ?? run.issueKey
}

export function needsAttention(run: Run): boolean {
  return run.stateKind === 'blocked' || run.stateKind === 'failed'
}

export function groupRunsByIssue(runs: Run[]): IssueGroup[] {
  const ordered = [...runs].sort((a, b) => seconds(b.lastObservedAt) - seconds(a.lastObservedAt) || runKey(a).localeCompare(runKey(b)))
  const groups = new Map<string, IssueGroup>()
  for (const run of ordered) {
    const group = groups.get(run.issueKey)
    if (group) group.runs.push(run)
    else groups.set(run.issueKey, { issueKey: run.issueKey, latest: run, runs: [run] })
  }
  return [...groups.values()]
}

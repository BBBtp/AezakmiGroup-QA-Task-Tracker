import { useEffect, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"

type Job = {
  id: string
  issue_key: string
  status: "queued" | "running" | "unknown" | "completed" | "failed" | "interrupted"
  requested_at: string | null
  heartbeat_at: string | null
  telemetry_status: string | null
  error_code: string | null
}

const labels: Record<Job["status"], string> = {
  queued: "В очереди",
  running: "Работает на Mac",
  unknown: "Связь с Mac потеряна",
  completed: "Завершено",
  failed: "Ошибка",
  interrupted: "Прервано",
}

export function CodexJobs() {
  const [issueKey, setIssueKey] = useState("")
  const [jobs, setJobs] = useState<Job[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pendingId = useRef<string | null>(null)

  async function load() {
    try {
      const response = await fetch("/api/codex/jobs", { cache: "no-store" })
      if (!response.ok) throw new Error(response.status === 403 ? "Доступ к заданиям Codex не настроен." : "Не удалось прочитать очередь.")
      const data = await response.json() as { jobs: Job[] }
      setJobs(data.jobs)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Нет связи с очередью.")
    }
  }

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => { void load() }, 10_000)
    return () => window.clearInterval(timer)
  }, [])

  async function submit() {
    const normalized = issueKey.trim().toUpperCase()
    if (!/^[A-Z][A-Z0-9_]*-[1-9]\d*$/.test(normalized)) {
      setError("Укажи ключ задачи, например FRONT-187.")
      return
    }
    setBusy(true)
    try {
      pendingId.current ??= crypto.randomUUID()
      const response = await fetch("/api/codex/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: pendingId.current, issue_key: normalized }),
      })
      if (!response.ok) throw new Error("Не удалось поставить задачу в очередь.")
      pendingId.current = null
      setIssueKey("")
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Нет связи с очередью.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="border-primary/20 bg-black/80">
      <CardContent className="space-y-5 p-5">
        <div>
          <h2 className="text-xl font-semibold text-white">Codex на Mac</h2>
          <p className="mt-1 text-sm text-zinc-400">Первая команда проверяет задачу в режиме чтения. Изменения файлов и внешние записи выключены.</p>
          <a className="mt-2 inline-block text-sm text-primary underline" href="/office/?source=agent-relay">Открыть Agent Office</a>
        </div>
        <div className="flex flex-wrap gap-2">
          <Input className="max-w-60 bg-zinc-950" aria-label="Ключ задачи" placeholder="FRONT-187" value={issueKey}
            onChange={(event) => { setIssueKey(event.target.value); pendingId.current = null }} />
          <Button disabled={busy} onClick={() => void submit()}>Проверить задачу</Button>
        </div>
        {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
        <div className="space-y-2">
          {jobs.length === 0 && !error && <p className="text-sm text-zinc-400">Заданий пока нет.</p>}
          {jobs.map((job) => (
            <div key={job.id} className="rounded-lg border border-white/10 bg-zinc-950 p-3 text-sm">
              <div className="flex justify-between gap-3"><strong>{job.issue_key}</strong><span>{labels[job.status]}</span></div>
              <div className="mt-1 text-xs text-zinc-400">Run ID: {job.id}</div>
              {job.telemetry_status === "publish_failed" && <div className="mt-1 text-xs text-amber-300">Трасса не доставлена в MinIO</div>}
              {job.error_code && <div className="mt-1 text-xs text-rose-300">Код ошибки: {job.error_code}</div>}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

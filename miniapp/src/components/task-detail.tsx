import type { ReactNode } from "react"
import { Archive, ChevronDown, ExternalLink, Loader2, Link2, RotateCcw, TextSearch, Trash2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { taskDisplayStatus, taskDisplayStatusLabel } from "@/lib/task-status"
import type { TaskDetail } from "@/types"

export function TaskDetailPanel({
  task,
  archiveView,
  busyAction,
  onArchive,
  onRestore,
  onDeleteForever,
}: {
  task: TaskDetail | null
  archiveView: boolean
  busyAction: "archive" | "restore" | "delete" | null
  onArchive: () => void
  onRestore: () => void
  onDeleteForever: () => void
}) {
  if (!task) {
    return (
      <Card className="border-primary/15 bg-black/80">
        <CardContent className="flex min-h-[420px] items-center justify-center text-center text-muted-foreground">
          Выберите задачу слева, чтобы увидеть ссылки, raw text и историю событий.
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="border-primary/15 bg-black/85">
      <CardHeader className="space-y-4 p-4 sm:p-6">
        <div className="flex flex-wrap items-center gap-2 sm:gap-3">
          <Badge className="border border-primary/20 bg-primary/15 text-primary">{task.task_key}</Badge>
          <Badge variant="outline" className={statusBadgeClass(task.status, task.assignee)}>
            {taskDisplayStatusLabel(task.status, task.assignee)}
          </Badge>
        </div>
        <CardTitle className="text-xl sm:text-2xl">{task.app_name || task.title}</CardTitle>
        <CardDescription>Исполнитель назначается реакцией тестировщика на исходное сообщение задачи.</CardDescription>
        <div className="flex flex-wrap gap-2">
          {archiveView ? (
            <>
              <Button className="gap-2" disabled={busyAction !== null} onClick={onRestore} size="sm" variant="outline">
                {busyAction === "restore" ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
                Вернуть
              </Button>
              <Button
                className="gap-2 border-rose-500/30 text-rose-300 hover:bg-rose-500/10 hover:text-rose-200"
                disabled={busyAction !== null}
                onClick={onDeleteForever}
                size="sm"
                variant="outline"
              >
                {busyAction === "delete" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                Удалить навсегда
              </Button>
            </>
          ) : (
            <Button className="gap-2" disabled={busyAction !== null} onClick={onArchive} size="sm" variant="outline">
              {busyAction === "archive" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Archive className="h-4 w-4" />}
              В архив
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-5 p-4 pt-0 sm:space-y-6 sm:p-6 sm:pt-0">
        <div className="grid gap-4 md:grid-cols-2">
          <Info title="Исполнитель" value={task.assignee || "Еще не назначен"} icon={<TextSearch className="h-4 w-4" />} />
          <LinkCard title="Figma" href={task.figma_url} />
          <LinkCard title="GitHub" href={task.github_url} />
          <LinkCard title="Отчёт" href={task.report_url} />
        </div>

        <section className="space-y-3">
          <h3 className="text-sm uppercase tracking-[0.25em] text-muted-foreground">История</h3>
          <div className="space-y-5">
            {groupEventsByDay(task.events).map((group, index) => (
              <details
                key={group.dayKey}
                className="history-day overflow-hidden rounded-2xl border border-primary/10 bg-zinc-950/70"
                open={index === 0}
              >
                <summary className="history-day-summary flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 marker:hidden">
                  <div>
                    <div className="text-xs uppercase tracking-[0.2em] text-zinc-500">{group.label}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {group.events.length} {pluralizeEvents(group.events.length)}
                    </div>
                  </div>
                  <ChevronDown className="history-day-chevron h-4 w-4 text-muted-foreground" />
                </summary>
                <div className="history-day-content">
                  <div className="history-day-content-inner space-y-3 border-t border-primary/10 px-3 py-3 sm:px-4">
                    {group.events.map((event) => (
                      <Card key={event.id} className="border-primary/10 bg-zinc-950/90">
                        <CardContent className="p-4">
                          <div className="mb-2 flex items-center justify-between gap-2">
                            <Badge className={eventBadgeClass(event.event_type, event.message_text)}>
                              {eventLabel(event.event_type, event.message_text)}
                            </Badge>
                            <span className="text-xs text-muted-foreground">{formatTime(event.created_at)}</span>
                          </div>
                          <p className="whitespace-pre-wrap text-sm text-zinc-200">{event.message_text}</p>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                </div>
              </details>
            ))}
          </div>
        </section>
      </CardContent>
    </Card>
  )
}

function Info({ title, value, icon }: { title: string; value: string; icon: ReactNode }) {
  return (
    <div className="rounded-2xl border border-primary/10 bg-zinc-950 p-4">
      <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-muted-foreground">
        <span className="text-primary">{icon}</span>
        {title}
      </div>
      <div className="break-words text-sm text-white">{value}</div>
    </div>
  )
}

function LinkCard({ title, href }: { title: string; href: string | null }) {
  return (
    <Card className="border-primary/10 bg-zinc-950">
      <CardContent className="p-4">
        <div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-muted-foreground">
          <Link2 className="h-4 w-4 text-primary" />
          {title}
        </div>
        {href ? (
          <a className="inline-flex items-center gap-2 text-sm text-primary hover:underline" href={href} rel="noreferrer" target="_blank">
            Открыть
            <ExternalLink className="h-4 w-4" />
          </a>
        ) : (
          <div className="text-sm text-muted-foreground">Не прикреплено</div>
        )}
      </CardContent>
    </Card>
  )
}

function statusBadgeClass(status: TaskDetail["status"], assignee?: string | null) {
  const map: Record<TaskDetail["status"] | "unassigned", string> = {
    assigned: "border-amber-500/20 bg-amber-500/10 text-amber-300",
    done: "border-emerald-500/20 bg-emerald-500/10 text-emerald-300",
    paused: "border-zinc-500/20 bg-zinc-500/10 text-zinc-300",
    unassigned: "border-zinc-500/20 bg-zinc-500/10 text-zinc-300",
  }
  return map[taskDisplayStatus(status, assignee)]
}

function eventLabel(eventType: string, messageText: string) {
  if (eventType === "updated" && looksLikeFix(messageText)) {
    return "Фикс"
  }

  const map: Record<string, string> = {
    created: "Создано",
    updated: "Обновлено",
    done: "Завершено",
    report: "Отчёт",
    review: "Замечания",
    question: "Вопрос",
    comment: "Комментарий",
  }
  return map[eventType] ?? eventType
}

function eventBadgeClass(eventType: string, messageText: string) {
  if (eventType === "updated" && looksLikeFix(messageText)) {
    return "bg-amber-500/20 text-amber-200"
  }

  const map: Record<string, string> = {
    created: "bg-sky-500/15 text-sky-300",
    updated: "bg-amber-500/15 text-amber-300",
    done: "bg-emerald-500/15 text-emerald-300",
    report: "bg-cyan-500/15 text-cyan-300",
    review: "bg-rose-500/15 text-rose-300",
    question: "bg-violet-500/15 text-violet-300",
    comment: "bg-slate-500/15 text-slate-300",
  }
  return map[eventType] ?? "bg-slate-500/15 text-slate-300"
}

function formatDateTime(value: string | null) {
  if (!value) {
    return "—"
  }

  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Europe/Moscow",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date)
}

function formatTime(value: string | null) {
  if (!value) {
    return "—"
  }

  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Europe/Moscow",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date)
}

function groupEventsByDay(events: TaskDetail["events"]) {
  const groups = new Map<string, TaskDetail["events"]>()

  for (const event of events) {
    const dayKey = getDayKey(event.created_at)
    const existing = groups.get(dayKey) ?? []
    existing.push(event)
    groups.set(dayKey, existing)
  }

  return Array.from(groups.entries())
    .map(([dayKey, dayEvents]) => ({
      dayKey,
      label: formatDayLabel(dayKey),
      events: [...dayEvents].reverse(),
    }))
    .reverse()
}

function getDayKey(value: string | null) {
  if (!value) {
    return "unknown"
  }

  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Moscow",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date)
}

function formatDayLabel(dayKey: string) {
  if (dayKey === "unknown") {
    return "Без даты"
  }

  const date = new Date(`${dayKey}T00:00:00+03:00`)
  if (Number.isNaN(date.getTime())) {
    return dayKey
  }

  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Europe/Moscow",
    day: "2-digit",
    month: "long",
    year: "numeric",
  }).format(date)
}

function looksLikeFix(messageText: string) {
  const lowered = messageText.toLowerCase()
  return [
    "исправил",
    "исправили",
    "фикс",
    "залил фикс",
    "пофиксил",
    "пофиксили",
    "fixed",
    "fix",
    "поправили",
    "обновили",
    "перезалил",
    "перезалили",
  ].some((token) => lowered.includes(token))
}

function pluralizeEvents(count: number) {
  const mod10 = count % 10
  const mod100 = count % 100

  if (mod10 === 1 && mod100 !== 11) {
    return "событие"
  }
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return "события"
  }
  return "событий"
}

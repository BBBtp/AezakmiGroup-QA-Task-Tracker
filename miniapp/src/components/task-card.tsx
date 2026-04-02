import type { ReactNode } from "react"
import { CheckCircle2, CircleDashed, FileText, PauseCircle, Rows3 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { taskDisplayStatus, taskDisplayStatusLabel } from "@/lib/task-status"
import { cn } from "@/lib/utils"
import type { TaskSummary } from "@/types"

const statusMap = {
  assigned: {
    icon: CircleDashed,
    className: "text-amber-300",
  },
  done: {
    icon: CheckCircle2,
    className: "text-emerald-300",
  },
  paused: {
    icon: PauseCircle,
    className: "text-zinc-300",
  },
  unassigned: {
    icon: Rows3,
    className: "text-zinc-300",
  },
}

type TaskCardProps = {
  task: TaskSummary
  selected: boolean
  onClick: () => void
  viewMode: "cards" | "list"
}

export function TaskCard({ task, selected, onClick, viewMode }: TaskCardProps) {
  const displayStatus = taskDisplayStatus(task.status, task.assignee)
  const status = statusMap[displayStatus]
  const StatusIcon = status.icon
  const statusLabel = taskDisplayStatusLabel(task.status, task.assignee)

  if (viewMode === "list") {
    return (
      <button className="block w-full text-left" onClick={onClick} type="button">
        <Card
          className={cn(
            "w-full overflow-hidden border-primary/15 bg-black/80 backdrop-blur-sm transition hover:border-primary/60 hover:bg-zinc-950/95",
            selected && "border-primary bg-[linear-gradient(135deg,rgba(255,212,0,0.12),rgba(255,255,255,0.04))] shadow-[0_0_0_1px_rgba(255,212,0,0.2)]",
          )}
        >
          <CardContent className="flex w-full items-start justify-between gap-3 p-3.5">
            <div className="min-w-0 flex-1">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <Badge variant="outline" className={cn("gap-1 border-white/10 bg-black/20 px-2 py-1", status.className)}>
                  <StatusIcon className="h-3.5 w-3.5" />
                  {statusLabel}
                </Badge>
                <span className="text-xs text-muted-foreground">{task.task_key}</span>
              </div>

              <div className="line-clamp-2 text-base font-semibold text-white">{task.app_name || task.title}</div>

              <div className="mt-2.5 grid gap-1 text-sm">
                <AttributeRow label="Исполнитель" value={task.assignee || "Еще не назначен"} />
                <AttributeRow label="Чат" value={buildChatLabelFromTask(task)} />
              </div>

              <div className="mt-2.5 flex flex-wrap gap-2">
                <ActionIconButton href={task.figma_url} icon={<FigmaMark className="h-4 w-4" />} label="Figma" />
                <ActionIconButton href={task.github_url} icon={<GitHubMark className="h-4 w-4" />} label="GitHub" />
                <ActionIconButton href={task.report_url} icon={<FileText className="h-4 w-4" />} label="Отчёт" />
              </div>
            </div>
          </CardContent>
        </Card>
      </button>
    )
  }

  return (
    <button className="block w-full text-left" onClick={onClick} type="button">
      <Card
        className={cn(
          "w-full overflow-hidden border-primary/15 bg-black/80 backdrop-blur-sm transition hover:border-primary/60 hover:bg-zinc-950/95",
          selected && "border-primary bg-[linear-gradient(135deg,rgba(255,212,0,0.12),rgba(255,255,255,0.04))] shadow-[0_0_0_1px_rgba(255,212,0,0.2)]",
        )}
      >
        <CardHeader className="gap-2.5 p-3.5 sm:min-h-[112px] sm:p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Badge variant="outline" className={cn("gap-1 border-white/10 bg-black/20 px-2 py-1", status.className)}>
              <StatusIcon className="h-3.5 w-3.5" />
              {statusLabel}
            </Badge>
            <span className="text-xs text-muted-foreground">{task.task_key}</span>
          </div>
          <CardTitle className="line-clamp-2 text-base sm:text-lg">{task.app_name || task.title}</CardTitle>
        </CardHeader>

        <CardContent className="space-y-2.5 p-3.5 pt-0 text-sm sm:p-4 sm:pt-0">
          <div className="grid gap-2">
            <Meta label="Исполнитель" value={task.assignee || "Еще не назначен"} />
            <Meta label="Чат" value={buildChatLabelFromTask(task)} />
          </div>

          <div className="flex flex-wrap gap-2">
            <ActionIconButton href={task.figma_url} icon={<FigmaMark className="h-4 w-4" />} label="Figma" />
            <ActionIconButton href={task.github_url} icon={<GitHubMark className="h-4 w-4" />} label="GitHub" />
            <ActionIconButton href={task.report_url} icon={<FileText className="h-4 w-4" />} label="Отчёт" />
          </div>
        </CardContent>
      </Card>
    </button>
  )
}

function AttributeRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-sm text-zinc-300">
      <span className="text-zinc-500">{label}:</span> <span className="text-white">{value}</span>
    </div>
  )
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-primary/10 bg-zinc-950/80 p-2 sm:p-2.5">
      <div className="text-sm text-zinc-300">
        <span className="text-zinc-500">{label}:</span> <span className="text-white">{value}</span>
      </div>
    </div>
  )
}

function ActionIconButton({ href, icon, label }: { href: string | null; icon: ReactNode; label: string }) {
  if (!href) {
    return null
  }

  return (
    <a
      aria-label={label}
      className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-primary/20 bg-primary/10 text-primary transition hover:bg-primary/15"
      href={href}
      onClick={(event) => event.stopPropagation()}
      rel="noreferrer"
      target="_blank"
      title={label}
    >
      {icon}
    </a>
  )
}

function buildChatLabelFromTask(task: TaskSummary) {
  if (task.chat_title) {
    return task.chat_title
  }
  if (task.chat_username) {
    return `@${task.chat_username}`
  }
  return `Чат ${task.chat_id}`
}

function FigmaMark({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <rect x="5" y="2" width="7" height="7" rx="3.5" fill="#F24E1E" />
      <rect x="5" y="9" width="7" height="7" rx="3.5" fill="#A259FF" />
      <rect x="5" y="16" width="7" height="7" rx="3.5" fill="#0ACF83" />
      <rect x="12" y="2" width="7" height="7" rx="3.5" fill="#FF7262" />
      <circle cx="15.5" cy="12.5" r="3.5" fill="#1ABCFE" />
    </svg>
  )
}

function GitHubMark({ className }: { className?: string }) {
  return (
    <svg className={className} fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M12 2.25a9.75 9.75 0 0 0-3.084 19.002c.487.09.665-.211.665-.47 0-.233-.009-.85-.014-1.668-2.705.587-3.276-1.304-3.276-1.304-.442-1.122-1.08-1.422-1.08-1.422-.883-.604.067-.592.067-.592.976.069 1.49 1.003 1.49 1.003.867 1.486 2.276 1.057 2.83.809.088-.628.339-1.057.617-1.3-2.159-.245-4.428-1.08-4.428-4.807 0-1.062.38-1.93 1.003-2.61-.1-.246-.435-1.236.095-2.578 0 0 .818-.262 2.68.998A9.328 9.328 0 0 1 12 6.97c.826.004 1.66.111 2.438.327 1.86-1.26 2.676-.998 2.676-.998.532 1.342.197 2.332.097 2.578.625.68 1 1.548 1 2.61 0 3.736-2.273 4.559-4.438 4.799.349.3.66.894.66 1.803 0 1.302-.012 2.352-.012 2.672 0 .261.176.565.672.469A9.75 9.75 0 0 0 12 2.25Z" />
    </svg>
  )
}

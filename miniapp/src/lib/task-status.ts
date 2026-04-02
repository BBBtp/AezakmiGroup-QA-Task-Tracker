import type { TaskStatus } from "@/types"

export function taskStatusLabel(status: TaskStatus): string {
  const labels: Record<TaskStatus, string> = {
    assigned: "В работе",
    done: "Готово",
    paused: "Пауза",
  }
  return labels[status]
}

export function taskDisplayStatus(status: TaskStatus, assignee?: string | null): TaskStatus | "unassigned" {
  if (status === "assigned" && !assignee) {
    return "unassigned"
  }

  return status
}

export function taskDisplayStatusLabel(status: TaskStatus, assignee?: string | null): string {
  const displayStatus = taskDisplayStatus(status, assignee)
  if (displayStatus === "unassigned") {
    return "Не взято"
  }

  return taskStatusLabel(displayStatus)
}

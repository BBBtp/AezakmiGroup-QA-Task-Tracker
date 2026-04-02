export type TaskStatus = "assigned" | "done" | "paused"

export type TaskSummary = {
  id: number
  task_key: string
  app_name: string | null
  title: string
  status: TaskStatus
  assignee: string | null
  chat_id: number
  chat_title: string | null
  chat_username: string | null
  report_url: string | null
  figma_url: string | null
  github_url: string | null
  archive_url: string | null
  branch_name: string | null
  relevant_file_path: string | null
  relevant_line_number: number | null
  is_archived: boolean
  archived_at: string | null
  created_at: string | null
  completed_at: string | null
  last_activity_at: string | null
  last_event_text: string | null
  last_event_type: string | null
  has_review: boolean
}

export type TaskEvent = {
  id: number
  event_type: string
  message_text: string
  created_at: string | null
}

export type TaskDetail = TaskSummary & {
  raw_text: string
  events: TaskEvent[]
}

export type ChatSummary = {
  id: number
  title: string | null
  username: string | null
}

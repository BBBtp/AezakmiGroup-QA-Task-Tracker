import { useEffect, useMemo, useRef, useState } from "react"
import { ArrowLeft, CalendarDays, ChevronDown, ChevronLeft, ChevronRight, Loader2, RefreshCw, Search, X } from "lucide-react"

import { TaskCard } from "@/components/task-card"
import { TaskDetailPanel } from "@/components/task-detail"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { getTelegramInitData, initTelegramWebApp } from "@/lib/telegram"
import { taskDisplayStatus } from "@/lib/task-status"
import type { ChatSummary, TaskDetail, TaskSummary } from "@/types"

export default function App() {
  const companyMarkUrl = "/miniapp/company-mark.svg"
  const today = formatDateInput(new Date())
  const statusOptions = [
    ["all", "Все"],
    ["assigned", "В работе"],
    ["unassigned", "Не взято"],
    ["done", "Готово"],
  ] as const
  const quickFilterOptions = [
    ["all", "Все"],
    ["unassigned", "Без исполнителя"],
    ["has_figma", "С макетом"],
    ["no_figma", "Без макета"],
    ["has_review", "С замечаниями"],
  ] as const
  const assigneeOptions = [
    ["all", "Все исполнители"],
    ["Богдан", "Богдан"],
    ["Глеб", "Глеб"],
  ] as const
  const [archiveView, setArchiveView] = useState(false)
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [chats, setChats] = useState<ChatSummary[]>([])
  const [selectedTask, setSelectedTask] = useState<TaskDetail | null>(null)
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null)
  const [query, setQuery] = useState("")
  const [status, setStatus] = useState<"all" | "assigned" | "unassigned" | "done" | "paused">("all")
  const [quickFilter, setQuickFilter] = useState<"all" | "unassigned" | "has_figma" | "no_figma" | "has_review">("all")
  const [assigneeFilter, setAssigneeFilter] = useState<"all" | "Богдан" | "Глеб">("all")
  const [selectedChatId, setSelectedChatId] = useState<number | null>(null)
  const [chatQuery, setChatQuery] = useState("")
  const [chatDropdownOpen, setChatDropdownOpen] = useState(false)
  const [dateFrom, setDateFrom] = useState("")
  const [dateTo, setDateTo] = useState("")
  const desktopChatDropdownRef = useRef<HTMLDivElement | null>(null)
  const mobileChatDropdownRef = useRef<HTMLDivElement | null>(null)
  const selectedTaskIdRef = useRef<number | null>(null)
  const tasksSnapshotRef = useRef("")
  const chatsSnapshotRef = useRef("")
  const [loading, setLoading] = useState(true)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [taskActionLoading, setTaskActionLoading] = useState<"archive" | "restore" | "delete" | null>(null)
  const [authState, setAuthState] = useState<"checking" | "authorized" | "blocked">("checking")
  const [authError, setAuthError] = useState("")
  const [liveStatus, setLiveStatus] = useState<"connecting" | "connected" | "error">("connecting")
  const [lastLiveEvent, setLastLiveEvent] = useState("—")
  const [lastLiveAt, setLastLiveAt] = useState("—")

  useEffect(() => {
    const webApp = initTelegramWebApp()
    const initData = getTelegramInitData()

    if (!webApp || !initData) {
      setAuthState("blocked")
      setAuthError("Мини-приложение доступно только из Telegram.")
      setLoading(false)
      return
    }

    void authenticateMiniApp(initData)
  }, [])

  useEffect(() => {
    selectedTaskIdRef.current = selectedTaskId
  }, [selectedTaskId])

  useEffect(() => {
    tasksSnapshotRef.current = JSON.stringify(tasks)
  }, [tasks])

  useEffect(() => {
    chatsSnapshotRef.current = JSON.stringify(chats)
  }, [chats])

  useEffect(() => {
    if (authState !== "authorized") {
      return
    }
    void loadTasks()
  }, [archiveView, authState])

  useEffect(() => {
    if (authState !== "authorized") {
      return
    }
    setLiveStatus("connecting")
    const eventSource = new EventSource("/api/stream")

    eventSource.onopen = () => {
      setLiveStatus("connected")
    }

    eventSource.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as { type?: string; task_id?: number }
        setLastLiveEvent(payload.type ? `${payload.type}${payload.task_id ? ` #${payload.task_id}` : ""}` : event.data)
        setLastLiveAt(new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" }))
        void loadTasks(false)
        if (selectedTaskIdRef.current !== null && (!payload.task_id || payload.task_id === selectedTaskIdRef.current)) {
          void loadTaskDetail(selectedTaskIdRef.current, false)
        }
      } catch {
        setLastLiveEvent("raw_event")
        setLastLiveAt(new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" }))
        void loadTasks(false)
        if (selectedTaskIdRef.current !== null) {
          void loadTaskDetail(selectedTaskIdRef.current, false)
        }
      }
    }

    eventSource.onerror = () => {
      setLiveStatus("error")
    }

    return () => {
      eventSource.close()
    }
  }, [archiveView, authState])

  useEffect(() => {
    if (authState !== "authorized") {
      return
    }

    const intervalId = window.setInterval(() => {
      void loadTasks(false)
      if (selectedTaskIdRef.current !== null) {
        void loadTaskDetail(selectedTaskIdRef.current, false)
      }
      setLastLiveAt(new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" }))
      if (liveStatus !== "connected") {
        setLastLiveEvent("poll_refresh")
      }
    }, 5000)

    return () => {
      window.clearInterval(intervalId)
    }
  }, [archiveView, authState, liveStatus])

  useEffect(() => {
    if (!chatDropdownOpen) {
      return
    }

    function handlePointer(event: MouseEvent | TouchEvent) {
      const target = event.target as Node
      const insideDesktop = desktopChatDropdownRef.current?.contains(target) ?? false
      const insideMobile = mobileChatDropdownRef.current?.contains(target) ?? false
      if (!insideDesktop && !insideMobile) {
        setChatDropdownOpen(false)
      }
    }

    document.addEventListener("mousedown", handlePointer)
    document.addEventListener("touchstart", handlePointer)
    return () => {
      document.removeEventListener("mousedown", handlePointer)
      document.removeEventListener("touchstart", handlePointer)
    }
  }, [chatDropdownOpen])

  useEffect(() => {
    if (authState !== "authorized" || selectedTaskId === null) {
      return
    }
    void loadTaskDetail(selectedTaskId)
  }, [authState, selectedTaskId])

  const filteredTasks = useMemo(() => {
    return tasks
      .filter((task) => {
        const displayStatus = taskDisplayStatus(task.status, task.assignee)
        const statusMatch =
          status === "all" ||
          (status === "assigned" && displayStatus === "assigned") ||
          (status === "unassigned" && displayStatus === "unassigned") ||
          task.status === status
        const assigneeMatch = assigneeFilter === "all" || task.assignee === assigneeFilter
        const quickMatch =
          quickFilter === "all" ||
          (quickFilter === "unassigned" && displayStatus === "unassigned") ||
          (quickFilter === "has_figma" && Boolean(task.figma_url)) ||
          (quickFilter === "no_figma" && !task.figma_url) ||
          (quickFilter === "has_review" && task.has_review)
        const chatMatch = selectedChatId === null || task.chat_id === selectedChatId
        const createdAt = parseDate(task.created_at)
        const fromMatch = !dateFrom || createdAt >= parseDateStart(dateFrom)
        const toMatch = !dateTo || createdAt <= parseDateEnd(dateTo)
        const haystack = [
          task.task_key,
          task.app_name,
          task.title,
          task.assignee,
          task.branch_name,
          task.chat_title,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
        const queryMatch = haystack.includes(query.toLowerCase())
        return statusMatch && assigneeMatch && quickMatch && queryMatch && chatMatch && fromMatch && toMatch
      })
      .sort((left, right) => parseDate(right.created_at) - parseDate(left.created_at))
  }, [assigneeFilter, dateFrom, dateTo, query, quickFilter, selectedChatId, status, tasks])

  const filteredChats = useMemo(() => {
    const needle = chatQuery.trim().toLowerCase()
    if (!needle) {
      return chats
    }
    return chats.filter((chat) => {
      const label = buildChatLabel(chat).toLowerCase()
      return label.includes(needle)
    })
  }, [chatQuery, chats])

  const testerMetrics = useMemo(() => {
    const testers = ["Богдан", "Глеб"]
    return testers.map((tester) => {
      const testerTasks = tasks.filter((task) => task.assignee === tester)
      return {
        name: tester,
        total: testerTasks.length,
        assigned: testerTasks.filter((task) => task.status === "assigned").length,
        done: testerTasks.filter((task) => task.status === "done").length,
      }
    })
  }, [tasks])

  const metricBreakdown = useMemo(() => {
    return {
      total: testerMetrics.map((metric) => ({ name: metric.name, value: metric.total })),
      assigned: testerMetrics.map((metric) => ({ name: metric.name, value: metric.assigned })),
      done: testerMetrics.map((metric) => ({ name: metric.name, value: metric.done })),
    }
  }, [testerMetrics])

  const unassignedTasks = useMemo(() => {
    return tasks.filter((task) => task.status === "assigned" && !task.assignee)
  }, [tasks])

  const activeTasks = useMemo(() => {
    return tasks.filter((task) => task.status === "assigned" && Boolean(task.assignee))
  }, [tasks])

  async function loadTasks(showLoader = true) {
    if (showLoader) {
      setLoading(true)
    }
    const archivedQuery = archiveView ? "?archived=1" : ""
    const [tasksResponse, chatsResponse] = await Promise.all([
      fetch(`/api/tasks${archivedQuery}`),
      fetch(`/api/chats${archivedQuery}`),
    ])
    if (tasksResponse.status === 401 || chatsResponse.status === 401 || tasksResponse.status === 403 || chatsResponse.status === 403) {
      handleAuthFailure("Доступ к mini app разрешён только выбранным пользователям из Telegram.")
      return
    }
    const tasksPayload = (await tasksResponse.json()) as { tasks: TaskSummary[] }
    const chatsPayload = (await chatsResponse.json()) as { chats: ChatSummary[] }

    const nextTasksSnapshot = JSON.stringify(tasksPayload.tasks)
    const nextChatsSnapshot = JSON.stringify(chatsPayload.chats)

    if (tasksSnapshotRef.current !== nextTasksSnapshot) {
      setTasks(tasksPayload.tasks)
    }
    if (chatsSnapshotRef.current !== nextChatsSnapshot) {
      setChats(chatsPayload.chats)
    }

    if (selectedTaskId !== null && !tasksPayload.tasks.some((task) => task.id === selectedTaskId)) {
      setSelectedTaskId(null)
      setSelectedTask(null)
    }
    if (showLoader) {
      setLoading(false)
    }
  }

  async function loadTaskDetail(taskId: number, showLoader = true) {
    if (showLoader) {
      setLoadingDetail(true)
    }
    const response = await fetch(`/api/tasks/${taskId}`)
    if (response.status === 401 || response.status === 403) {
      handleAuthFailure("Сессия mini app истекла или доступ запрещён.")
      return
    }
    if (!response.ok) {
      setSelectedTask(null)
      setSelectedTaskId(null)
      if (showLoader) {
        setLoadingDetail(false)
      }
      return
    }
    const payload = (await response.json()) as TaskDetail
    setSelectedTask(payload)
    if (showLoader) {
      setLoadingDetail(false)
    }
  }

  function exportReport() {
    const rows = filteredTasks.map((task) => {
      const title = task.app_name || task.task_key
      const track = buildExportTrack(task)
      const tester = exportTester(task.assignee)
      const statusLabel = reportStatus(task)
      return [title, track, "", task.figma_url ?? "", tester, statusLabel]
    })

    const header = ["App", "Track", "Description", "Mockup", "Tester", "Status"]
    const csv = `sep=;\r\n${[header, ...rows].map((row) => row.map(escapeCsv).join(";")).join("\r\n")}`
    const blob = new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8;" })
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = buildExportFilename(dateFrom, dateTo)
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  }

  function handleSelectTask(taskId: number) {
    setSelectedTaskId(taskId)
  }

  function handleBackToList() {
    setSelectedTaskId(null)
    setSelectedTask(null)
  }

  async function mutateTask(taskId: number, action: "archive" | "restore" | "delete") {
    setTaskActionLoading(action)
    try {
      const response = await fetch(
        action === "delete" ? `/api/tasks/${taskId}` : `/api/tasks/${taskId}/${action}`,
        { method: action === "delete" ? "DELETE" : "POST" },
      )
      if (response.status === 401 || response.status === 403) {
        handleAuthFailure("Сессия mini app истекла или доступ запрещён.")
        return
      }
      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`)
      }
      setSelectedTaskId(null)
      setSelectedTask(null)
      await loadTasks(false)
    } finally {
      setTaskActionLoading(null)
    }
  }

  async function authenticateMiniApp(initData: string) {
    try {
      const response = await fetch("/api/auth/telegram", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ init_data: initData }),
      })
      if (!response.ok) {
        handleAuthFailure("Доступ к mini app разрешён только через Telegram и только для согласованных пользователей.")
        return
      }
      setAuthState("authorized")
      setAuthError("")
    } catch {
      handleAuthFailure("Не удалось подтвердить доступ к mini app.")
    }
  }

  function handleAuthFailure(message: string) {
    setAuthState("blocked")
    setAuthError(message)
    setLoading(false)
    setLoadingDetail(false)
    setTasks([])
    setChats([])
    setSelectedTask(null)
    setSelectedTaskId(null)
  }

  if (authState === "checking") {
    return (
      <div className="min-h-screen bg-background text-foreground">
        <div className="mx-auto flex min-h-screen max-w-[640px] items-center justify-center px-4">
          <Card className="w-full border-primary/20 bg-black/80">
            <CardContent className="flex min-h-[220px] items-center justify-center gap-3 p-6 text-white">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
              Проверяю доступ к mini app...
            </CardContent>
          </Card>
        </div>
      </div>
    )
  }

  if (authState === "blocked") {
    return (
      <div className="min-h-screen bg-background text-foreground">
        <div className="mx-auto flex min-h-screen max-w-[640px] items-center justify-center px-4">
          <Card className="w-full border-primary/20 bg-black/80">
            <CardContent className="space-y-3 p-6">
              <div className="text-lg font-semibold text-white">Доступ ограничен</div>
              <div className="text-sm leading-6 text-zinc-300">
                {authError || "Мини-приложение открывается только из Telegram Mini App и только для разрешённых пользователей."}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(255,212,0,0.06)_0%,transparent_20%,transparent_100%)]" />
      <div className="relative mx-auto flex max-w-[1500px] flex-col gap-3 px-3 py-3 sm:gap-4 sm:px-4 sm:py-4 md:px-6">
        <Card className="border-primary/15 bg-black/70">
          <CardContent className="flex flex-wrap items-center gap-4 px-4 py-3 text-xs text-zinc-300">
            <div>
              <span className="text-zinc-500">Live:</span>{" "}
              <span className={liveStatus === "connected" ? "text-emerald-300" : liveStatus === "error" ? "text-rose-300" : "text-amber-300"}>
                {liveStatus === "connected" ? "connected" : liveStatus === "error" ? "error" : "connecting"}
              </span>
            </div>
            <div>
              <span className="text-zinc-500">Last event:</span> {lastLiveEvent}
            </div>
            <div>
              <span className="text-zinc-500">Last refresh:</span> {lastLiveAt}
            </div>
          </CardContent>
        </Card>
        <header className={`grid gap-3 ${archiveView ? "lg:grid-cols-1" : "lg:grid-cols-[1.4fr,0.8fr]"}`}>
          <Card className="overflow-hidden border-primary/20 bg-black/80">
            <CardContent className="flex flex-col gap-2 p-4 sm:p-5">
              <div className="flex items-center gap-3 sm:gap-4">
                <img alt="Aezakmi Group" className="h-10 w-10 object-contain sm:h-14 sm:w-14" src={companyMarkUrl} />
                <div>
                  <div className="text-xs uppercase tracking-[0.42em] text-primary">Aezakmi Group</div>
                  <div className="text-lg font-semibold text-white sm:text-2xl md:text-[2rem]">QA Таск Трекер</div>
                </div>
              </div>
            </CardContent>
          </Card>

          {!archiveView ? (
            <Card className="border-primary/20 bg-black/80">
              <CardContent className="p-4 sm:p-5">
                <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                  <Stat
                    title="Всего"
                    value={String(tasks.length)}
                    breakdown={metricBreakdown.total}
                  />
                  <Stat
                    title="В работе"
                    value={String(activeTasks.length)}
                    breakdown={metricBreakdown.assigned}
                  />
                  <SimpleStat
                    title="Не взято"
                    value={String(unassignedTasks.length)}
                  />
                  <Stat
                    title="Готово"
                    value={String(tasks.filter((task) => task.status === "done").length)}
                    breakdown={metricBreakdown.done}
                  />
                </div>
              </CardContent>
            </Card>
          ) : null}
        </header>

        <section className="hidden gap-4 xl:grid xl:grid-cols-[460px,minmax(0,1fr)] xl:items-start">
          <Card className="border-primary/20 bg-black/80 xl:col-span-2">
            <CardContent className="space-y-4 p-3.5">
              <div className="grid gap-3 xl:grid-cols-[minmax(280px,1.05fr),260px,220px,320px] xl:items-end">
                <div className="space-y-1.5">
                  <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Поиск</div>
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      className="h-11 border-primary/15 bg-zinc-950 pl-9 text-white placeholder:text-zinc-500"
                      onChange={(event) => setQuery(event.target.value)}
                      placeholder="Поиск по ключу, приложению, ветке"
                      value={query}
                    />
                  </div>
                </div>

                <div className="space-y-1.5">
                  <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Чаты</div>
                  <div ref={desktopChatDropdownRef} className="relative">
                    <Button
                      className="h-11 w-full justify-between"
                      onClick={() => setChatDropdownOpen((current) => !current)}
                      size="sm"
                      variant="outline"
                    >
                      <span className="truncate">
                        {selectedChatId ? buildChatLabel(chats.find((chat) => chat.id === selectedChatId) ?? null) : "Все чаты"}
                      </span>
                      <ChevronDown
                        className={`h-4 w-4 text-muted-foreground transition-transform duration-200 ${
                          chatDropdownOpen ? "rotate-180" : ""
                        }`}
                      />
                    </Button>
                    {chatDropdownOpen ? (
                      <div className="absolute left-0 right-0 z-20 mt-2 overflow-hidden rounded-2xl border border-primary/20 bg-black/95 shadow-[0_20px_50px_rgba(0,0,0,0.45)]">
                        <div className="p-2">
                          <Input
                            className="border-primary/15 bg-zinc-950 text-sm text-white placeholder:text-zinc-500"
                            onChange={(event) => setChatQuery(event.target.value)}
                            placeholder="Поиск по чатам"
                            value={chatQuery}
                          />
                        </div>
                        <div className="max-h-56 overflow-y-auto border-t border-primary/10 p-2">
                          <button
                            className="flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm text-white hover:bg-white/5"
                            onClick={() => {
                              setSelectedChatId(null)
                              setChatDropdownOpen(false)
                            }}
                            type="button"
                          >
                            Все чаты
                          </button>
                          {filteredChats.map((chat) => (
                            <button
                              key={chat.id}
                              className="flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm text-white hover:bg-white/5"
                              onClick={() => {
                                setSelectedChatId(chat.id)
                                setChatDropdownOpen(false)
                              }}
                              type="button"
                            >
                              <span className="truncate">{buildChatLabel(chat)}</span>
                              {selectedChatId === chat.id ? <span className="text-primary">✓</span> : null}
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
                </div>

                <div className="space-y-1.5">
                  <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Режим</div>
                  <div className="inline-flex h-11 w-full items-center rounded-full border border-primary/15 bg-zinc-950 p-1">
                    <button
                      className={`flex-1 rounded-full px-3 py-2 text-sm font-medium transition ${
                        !archiveView ? "bg-primary text-black" : "text-white hover:bg-white/5"
                      }`}
                      onClick={() => setArchiveView(false)}
                      type="button"
                    >
                      Активные
                    </button>
                    <button
                      className={`flex-1 rounded-full px-3 py-2 text-sm font-medium transition ${
                        archiveView ? "bg-primary text-black" : "text-white hover:bg-white/5"
                      }`}
                      onClick={() => setArchiveView(true)}
                      type="button"
                    >
                      Архив
                    </button>
                  </div>
                </div>

                <div className="space-y-1.5">
                  <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Действия</div>
                  <div className="flex gap-2">
                    <Button className="h-11 flex-1 gap-2" onClick={() => void loadTasks()} variant="ghost">
                      <RefreshCw className="h-4 w-4" />
                      Обновить
                    </Button>
                    <Button className="h-11 flex-1 gap-2" onClick={exportReport} variant="outline">
                      Экспорт
                    </Button>
                  </div>
                </div>
              </div>

              <div className="grid gap-4 xl:grid-cols-[minmax(420px,1.8fr),minmax(220px,1fr),minmax(220px,1fr),minmax(220px,1fr)] xl:items-start">
                <DateRangeFilter
                  dateFrom={dateFrom}
                  dateTo={dateTo}
                  onReset={() => {
                    setDateFrom("")
                    setDateTo("")
                  }}
                  onSetDateFrom={setDateFrom}
                  onSetDateTo={setDateTo}
                  today={today}
                />

                <FilterDropdown
                  label="Статус"
                  onSelect={(value) => setStatus(value as typeof status)}
                  options={statusOptions}
                  value={status}
                />

                <FilterDropdown
                  label="Исполнитель"
                  onSelect={(value) => setAssigneeFilter(value as typeof assigneeFilter)}
                  options={assigneeOptions}
                  value={assigneeFilter}
                />

                <FilterDropdown
                  label="Быстрые фильтры"
                  onSelect={(value) => setQuickFilter(value as typeof quickFilter)}
                  options={quickFilterOptions}
                  value={quickFilter}
                />
              </div>
            </CardContent>
          </Card>

          <div className="space-y-3 xl:flex xl:max-h-[calc(100vh-18rem)] xl:flex-col xl:overflow-hidden">
            <Card className="hidden border-primary/20 bg-black/80">
              <CardContent className="space-y-3 p-3.5">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    className="border-primary/15 bg-zinc-950 pl-9 text-white placeholder:text-zinc-500"
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Поиск по ключу, приложению, ветке"
                    value={query}
                  />
                </div>

                <div className="space-y-1.5">
                  <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Режим</div>
                  <div className="flex flex-wrap gap-2">
                    <Button onClick={() => setArchiveView(false)} size="sm" variant={!archiveView ? "default" : "outline"}>
                      Активные
                    </Button>
                    <Button onClick={() => setArchiveView(true)} size="sm" variant={archiveView ? "default" : "outline"}>
                      Архив
                    </Button>
                  </div>
                </div>

                <div className="space-y-1.5">
                  <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Чаты</div>
                  <div ref={desktopChatDropdownRef} className="relative">
                    <Button
                      className="w-full justify-between"
                      onClick={() => setChatDropdownOpen((current) => !current)}
                      size="sm"
                      variant="outline"
                    >
                      <span className="truncate">
                        {selectedChatId ? buildChatLabel(chats.find((chat) => chat.id === selectedChatId) ?? null) : "Все чаты"}
                      </span>
                      <ChevronDown
                        className={`h-4 w-4 text-muted-foreground transition-transform duration-200 ${
                          chatDropdownOpen ? "rotate-180" : ""
                        }`}
                      />
                    </Button>
                    {chatDropdownOpen ? (
                      <div className="absolute left-0 right-0 z-20 mt-2 overflow-hidden rounded-2xl border border-primary/20 bg-black/95 shadow-[0_20px_50px_rgba(0,0,0,0.45)]">
                        <div className="p-2">
                          <Input
                            className="border-primary/15 bg-zinc-950 text-sm text-white placeholder:text-zinc-500"
                            onChange={(event) => setChatQuery(event.target.value)}
                            placeholder="Поиск по чатам"
                            value={chatQuery}
                          />
                        </div>
                        <div className="max-h-56 overflow-y-auto border-t border-primary/10 p-2">
                          <button
                            className="flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm text-white hover:bg-white/5"
                            onClick={() => {
                              setSelectedChatId(null)
                              setChatDropdownOpen(false)
                            }}
                            type="button"
                          >
                            Все чаты
                          </button>
                          {filteredChats.map((chat) => (
                            <button
                              key={chat.id}
                              className="flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm text-white hover:bg-white/5"
                              onClick={() => {
                                setSelectedChatId(chat.id)
                                setChatDropdownOpen(false)
                              }}
                              type="button"
                            >
                              <span className="truncate">{buildChatLabel(chat)}</span>
                              {selectedChatId === chat.id ? <span className="text-primary">✓</span> : null}
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
                </div>

                <DateRangeFilter
                  dateFrom={dateFrom}
                  dateTo={dateTo}
                  onReset={() => {
                    setDateFrom("")
                    setDateTo("")
                  }}
                  onSetDateFrom={setDateFrom}
                  onSetDateTo={setDateTo}
                  today={today}
                />

                <div className="space-y-1.5">
                  <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Статус</div>
                  <div className="flex flex-wrap gap-2">
                    {[
                      ["all", "Все"],
                      ["assigned", "В работе"],
                      ["unassigned", "Не взято"],
                      ["done", "Готово"],
                    ].map(([value, label]) => (
                      <Button
                        key={value}
                        className="whitespace-nowrap"
                        onClick={() => setStatus(value as typeof status)}
                        size="sm"
                        variant={status === value ? "default" : "outline"}
                      >
                        {label}
                      </Button>
                    ))}
                  </div>
                </div>

                <div className="space-y-1.5">
                  <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Быстрые фильтры</div>
                  <div className="flex gap-2 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                    {[
                      ["all", "Все"],
                      ["unassigned", "Без исполнителя"],
                      ["has_figma", "С макетом"],
                      ["no_figma", "Без макета"],
                      ["has_review", "С замечаниями"],
                    ].map(([value, label]) => (
                      <Button
                        key={value}
                        className="shrink-0"
                        onClick={() => setQuickFilter(value as typeof quickFilter)}
                        size="sm"
                        variant={quickFilter === value ? "default" : "outline"}
                      >
                        {label}
                      </Button>
                    ))}
                  </div>
                </div>

                <div className="space-y-1.5">
                  <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Исполнитель</div>
                  <div className="flex gap-2 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                    {[
                      ["all", "Все исполнители"],
                      ["Богдан", "Богдан"],
                      ["Глеб", "Глеб"],
                    ].map(([value, label]) => (
                      <Button
                        key={value}
                        className="shrink-0 whitespace-nowrap"
                        onClick={() => setAssigneeFilter(value as typeof assigneeFilter)}
                        size="sm"
                        variant={assigneeFilter === value ? "default" : "outline"}
                      >
                        {label}
                      </Button>
                    ))}
                  </div>
                </div>

                <div className="flex flex-col gap-2 sm:flex-row">
                  <Button className="w-full gap-2" onClick={() => void loadTasks()} variant="ghost">
                    <RefreshCw className="h-4 w-4" />
                    Обновить список
                  </Button>
                  <Button className="w-full gap-2" onClick={exportReport} variant="outline">
                    Экспорт отчёта
                  </Button>
                </div>
              </CardContent>
            </Card>

            <div className="flex flex-col gap-3 xl:min-h-0 xl:flex-1 xl:overflow-y-auto xl:pr-1">
              {loading
                ? Array.from({ length: 4 }).map((_, index) => (
                    <Card key={index} className="w-full border-primary/20 bg-black/80 p-5">
                      <Skeleton className="mb-4 h-6 w-24" />
                      <Skeleton className="mb-2 h-5 w-4/5" />
                      <Skeleton className="mb-2 h-4 w-full" />
                      <Skeleton className="h-4 w-2/3" />
                    </Card>
                  ))
                : filteredTasks.map((task) => (
                    <TaskCard
                      key={task.id}
                      onClick={() => handleSelectTask(task.id)}
                      selected={task.id === selectedTaskId}
                      task={task}
                      viewMode="list"
                    />
                  ))}
            </div>
          </div>

          <div className="xl:sticky xl:top-4 xl:max-h-[calc(100vh-18rem)] xl:overflow-y-auto xl:pr-1">
            {loadingDetail ? (
              <Card className="border-primary/20 bg-black/80">
                <CardContent className="flex min-h-[420px] items-center justify-center gap-3 text-muted-foreground">
                  <Loader2 className="h-5 w-5 animate-spin" />
                  Загружаю детали задачи...
                </CardContent>
              </Card>
            ) : (
              <TaskDetailPanel
                archiveView={archiveView}
                busyAction={taskActionLoading}
                onArchive={() => (selectedTask ? void mutateTask(selectedTask.id, "archive") : undefined)}
                onDeleteForever={() =>
                  selectedTask && window.confirm(`Удалить ${selectedTask.task_key} из базы навсегда?`)
                    ? void mutateTask(selectedTask.id, "delete")
                    : undefined
                }
                onRestore={() => (selectedTask ? void mutateTask(selectedTask.id, "restore") : undefined)}
                task={selectedTask}
              />
            )}
          </div>
        </section>

        <section className="space-y-4 xl:hidden">
          {selectedTaskId === null ? (
            <>
              <Card className="border-primary/20 bg-black/80">
                <CardContent className="space-y-4 p-4">
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      className="border-primary/15 bg-zinc-950 pl-9 text-white placeholder:text-zinc-500"
                      onChange={(event) => setQuery(event.target.value)}
                      placeholder="Поиск по ключу, приложению, ветке"
                      value={query}
                    />
                  </div>

                  <div className="space-y-2">
                    <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Режим</div>
                    <div className="flex flex-wrap gap-2">
                      <Button onClick={() => setArchiveView(false)} size="sm" variant={!archiveView ? "default" : "outline"}>
                        Активные
                      </Button>
                      <Button onClick={() => setArchiveView(true)} size="sm" variant={archiveView ? "default" : "outline"}>
                        Архив
                      </Button>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Чаты</div>
                    <div ref={mobileChatDropdownRef} className="relative">
                      <Button
                        className="w-full justify-between"
                        onClick={() => setChatDropdownOpen((current) => !current)}
                        size="sm"
                        variant="outline"
                      >
                        <span className="truncate">
                          {selectedChatId ? buildChatLabel(chats.find((chat) => chat.id === selectedChatId) ?? null) : "Все чаты"}
                        </span>
                        <ChevronDown
                          className={`h-4 w-4 text-muted-foreground transition-transform duration-200 ${
                            chatDropdownOpen ? "rotate-180" : ""
                          }`}
                        />
                      </Button>
                      {chatDropdownOpen ? (
                        <div className="absolute left-0 right-0 z-20 mt-2 overflow-hidden rounded-2xl border border-primary/20 bg-black/95 shadow-[0_20px_50px_rgba(0,0,0,0.45)]">
                          <div className="p-2">
                            <Input
                              className="border-primary/15 bg-zinc-950 text-sm text-white placeholder:text-zinc-500"
                              onChange={(event) => setChatQuery(event.target.value)}
                              placeholder="Поиск по чатам"
                              value={chatQuery}
                            />
                          </div>
                          <div className="max-h-56 overflow-y-auto border-t border-primary/10 p-2">
                            <button
                              className="flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm text-white hover:bg-white/5"
                              onClick={() => {
                                setSelectedChatId(null)
                                setChatDropdownOpen(false)
                              }}
                              type="button"
                            >
                              Все чаты
                            </button>
                            {filteredChats.map((chat) => (
                              <button
                                key={chat.id}
                                className="flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm text-white hover:bg-white/5"
                                onClick={() => {
                                  setSelectedChatId(chat.id)
                                  setChatDropdownOpen(false)
                                }}
                                type="button"
                              >
                                <span className="truncate">{buildChatLabel(chat)}</span>
                                {selectedChatId === chat.id ? <span className="text-primary">✓</span> : null}
                              </button>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  </div>

                  <DateRangeFilter
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    onReset={() => {
                      setDateFrom("")
                      setDateTo("")
                    }}
                    onSetDateFrom={setDateFrom}
                    onSetDateTo={setDateTo}
                    today={today}
                  />

                  <div className="space-y-2">
                    <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Статус</div>
                    <div className="flex flex-wrap gap-2">
                      {[
                        ["all", "Все"],
                        ["assigned", "В работе"],
                        ["unassigned", "Не взято"],
                        ["done", "Готово"],
                      ].map(([value, label]) => (
                        <Button
                          key={value}
                          className="whitespace-nowrap"
                          onClick={() => setStatus(value as typeof status)}
                          size="sm"
                          variant={status === value ? "default" : "outline"}
                        >
                          {label}
                        </Button>
                      ))}
                    </div>
                  </div>

                  <div className="space-y-2">
                    <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Быстрые фильтры</div>
                    <div className="flex gap-2 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                      {[
                        ["all", "Все"],
                        ["unassigned", "Без исполнителя"],
                        ["has_figma", "С макетом"],
                        ["no_figma", "Без макета"],
                        ["has_review", "С замечаниями"],
                      ].map(([value, label]) => (
                        <Button
                          key={value}
                          className="shrink-0"
                          onClick={() => setQuickFilter(value as typeof quickFilter)}
                          size="sm"
                          variant={quickFilter === value ? "default" : "outline"}
                        >
                          {label}
                        </Button>
                      ))}
                    </div>
                  </div>

                  <div className="space-y-2">
                    <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Исполнитель</div>
                    <div className="flex gap-2 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                      {[
                        ["all", "Все исполнители"],
                        ["Богдан", "Богдан"],
                        ["Глеб", "Глеб"],
                      ].map(([value, label]) => (
                        <Button
                          key={value}
                          className="shrink-0 whitespace-nowrap"
                          onClick={() => setAssigneeFilter(value as typeof assigneeFilter)}
                          size="sm"
                          variant={assigneeFilter === value ? "default" : "outline"}
                        >
                          {label}
                        </Button>
                      ))}
                    </div>
                  </div>

                  <div className="flex flex-col gap-2 sm:flex-row">
                    <Button className="w-full gap-2" onClick={() => void loadTasks()} variant="ghost">
                      <RefreshCw className="h-4 w-4" />
                      Обновить список
                    </Button>
                    <Button className="w-full gap-2" onClick={exportReport} variant="outline">
                      Экспорт отчёта
                    </Button>
                  </div>
                </CardContent>
              </Card>

              <div className="flex flex-col gap-3">
                {loading
                  ? Array.from({ length: 4 }).map((_, index) => (
                      <Card key={index} className="w-full border-primary/20 bg-black/80 p-5">
                        <Skeleton className="mb-4 h-6 w-24" />
                        <Skeleton className="mb-2 h-5 w-4/5" />
                        <Skeleton className="mb-2 h-4 w-full" />
                        <Skeleton className="h-4 w-2/3" />
                      </Card>
                    ))
                  : filteredTasks.map((task) => (
                      <TaskCard
                        key={task.id}
                        onClick={() => handleSelectTask(task.id)}
                        selected={task.id === selectedTaskId}
                        task={task}
                        viewMode="list"
                      />
                    ))}
              </div>
            </>
          ) : (
            <div className="space-y-4">
              <Button className="w-full justify-start gap-2" onClick={handleBackToList} variant="outline">
                <ArrowLeft className="h-4 w-4" />
                Назад к списку
              </Button>
              {loadingDetail ? (
                <Card className="border-primary/20 bg-black/80">
                  <CardContent className="flex min-h-[420px] items-center justify-center gap-3 text-muted-foreground">
                    <Loader2 className="h-5 w-5 animate-spin" />
                    Загружаю детали задачи...
                  </CardContent>
                </Card>
              ) : (
                <TaskDetailPanel
                  archiveView={archiveView}
                  busyAction={taskActionLoading}
                  onArchive={() => (selectedTask ? void mutateTask(selectedTask.id, "archive") : undefined)}
                  onDeleteForever={() =>
                    selectedTask && window.confirm(`Удалить ${selectedTask.task_key} из базы навсегда?`)
                      ? void mutateTask(selectedTask.id, "delete")
                      : undefined
                  }
                  onRestore={() => (selectedTask ? void mutateTask(selectedTask.id, "restore") : undefined)}
                  task={selectedTask}
                />
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

function Stat({
  title,
  value,
  breakdown,
}: {
  title: string
  value: string
  breakdown: Array<{ name: string; value: number }>
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) {
      return
    }

    function handlePointer(event: MouseEvent | TouchEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false)
      }
    }

    document.addEventListener("mousedown", handlePointer)
    document.addEventListener("touchstart", handlePointer)
    return () => {
      document.removeEventListener("mousedown", handlePointer)
      document.removeEventListener("touchstart", handlePointer)
    }
  }, [open])

  return (
    <div ref={rootRef} className="group relative rounded-2xl border border-primary/20 bg-zinc-950 p-3.5">
      <div className="text-[11px] uppercase tracking-[0.18em] text-zinc-400">{title}</div>
      <button
        className="mt-1.5 text-left text-2xl font-semibold text-primary sm:text-[1.75rem]"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        {value}
      </button>
      <div
        className={`absolute left-1/2 top-full z-20 mt-3 w-[220px] -translate-x-1/2 rounded-2xl border border-primary/20 bg-black/95 p-3 shadow-[0_16px_40px_rgba(0,0,0,0.45)] transition duration-150 ${
          open ? "opacity-100" : "pointer-events-none opacity-0 group-hover:opacity-100"
        }`}
      >
        <div className="absolute left-1/2 top-0 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rotate-45 border-l border-t border-primary/20 bg-black/95" />
        <div className="mb-2 text-[10px] uppercase tracking-[0.24em] text-zinc-500">По тестировщикам</div>
        <div className="space-y-2">
          {breakdown.map((item) => (
            <div key={item.name} className="flex items-center justify-between gap-3 text-sm">
              <span className="text-white">{item.name}</span>
              <span className="font-semibold text-primary">{item.value}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function SimpleStat({ title, value }: { title: string; value: string }) {
  return (
    <div className="rounded-2xl border border-primary/20 bg-zinc-950 p-3.5">
      <div className="text-[11px] uppercase tracking-[0.18em] text-zinc-400">{title}</div>
      <div className="mt-1.5 text-2xl font-semibold text-primary sm:text-[1.75rem]">{value}</div>
    </div>
  )
}

function DateRangeFilter({
  dateFrom,
  dateTo,
  today,
  onSetDateFrom,
  onSetDateTo,
  onReset,
}: {
  dateFrom: string
  dateTo: string
  today: string
  onSetDateFrom: (value: string) => void
  onSetDateTo: (value: string) => void
  onReset: () => void
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Период</div>
        {dateFrom || dateTo ? (
          <button
            className="inline-flex items-center gap-1 text-[10px] uppercase tracking-[0.18em] text-primary transition hover:text-primary/80"
            onClick={onReset}
            type="button"
          >
            <X className="h-3 w-3" />
            Сбросить
          </button>
        ) : null}
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <DateField
          label="С"
          max={dateTo || today}
          onChange={onSetDateFrom}
          value={dateFrom}
        />
        <DateField
          label="По"
          max={today}
          min={dateFrom || undefined}
          onChange={onSetDateTo}
          value={dateTo}
        />
      </div>
    </div>
  )
}

function FilterDropdown({
  label,
  value,
  options,
  onSelect,
}: {
  label: string
  value: string
  options: readonly (readonly [string, string])[]
  onSelect: (value: string) => void
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const selectedLabel = options.find(([optionValue]) => optionValue === value)?.[1] ?? "Выбрать"

  useEffect(() => {
    if (!open) {
      return
    }

    function handlePointer(event: MouseEvent | TouchEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false)
      }
    }

    document.addEventListener("mousedown", handlePointer)
    document.addEventListener("touchstart", handlePointer)
    return () => {
      document.removeEventListener("mousedown", handlePointer)
      document.removeEventListener("touchstart", handlePointer)
    }
  }, [open])

  return (
    <div ref={rootRef} className="space-y-1.5">
      <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">{label}</div>
      <div className="relative">
        <Button className="w-full justify-between" onClick={() => setOpen((current) => !current)} size="sm" variant="outline">
          <span className="truncate">{selectedLabel}</span>
          <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
        </Button>
        {open ? (
          <div className="absolute left-0 right-0 z-20 mt-2 overflow-hidden rounded-2xl border border-primary/20 bg-black/95 shadow-[0_20px_50px_rgba(0,0,0,0.45)]">
            <div className="max-h-64 overflow-y-auto p-2">
              {options.map(([optionValue, optionLabel]) => (
                <button
                  key={optionValue}
                  className="flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm text-white hover:bg-white/5"
                  onClick={() => {
                    onSelect(optionValue)
                    setOpen(false)
                  }}
                  type="button"
                >
                  <span className="truncate">{optionLabel}</span>
                  {value === optionValue ? <span className="text-primary">✓</span> : null}
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}

function DateField({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string
  value: string
  min?: string
  max?: string
  onChange: (value: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [visibleMonth, setVisibleMonth] = useState(() => monthSeed(value))
  const rootRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    setVisibleMonth(monthSeed(value))
  }, [value])

  useEffect(() => {
    if (!open) {
      return
    }

    function handlePointer(event: MouseEvent | TouchEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false)
      }
    }

    document.addEventListener("mousedown", handlePointer)
    document.addEventListener("touchstart", handlePointer)
    return () => {
      document.removeEventListener("mousedown", handlePointer)
      document.removeEventListener("touchstart", handlePointer)
    }
  }, [open])

  const weeks = useMemo(() => buildCalendarWeeks(visibleMonth), [visibleMonth])
  const minTime = min ? parseDateStart(min) : null
  const maxTime = max ? parseDateEnd(max) : null
  const selected = value ? toDateFromInput(value) : null

  return (
    <div ref={rootRef} className="relative space-y-1">
      <div className="text-[10px] uppercase tracking-[0.16em] text-zinc-600">{label}</div>
      <button
        className="flex h-10 w-full items-center justify-between rounded-md border border-primary/15 bg-zinc-950 px-3 text-left text-sm text-white transition hover:border-primary/30"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <span className={value ? "text-white" : "text-zinc-500"}>{value ? formatDateLabel(value) : "Выбрать дату"}</span>
        <CalendarDays className="h-4 w-4 text-primary" />
      </button>
      {open ? (
        <div className="absolute left-0 right-0 z-30 mt-2 overflow-hidden rounded-2xl border border-primary/20 bg-black/95 shadow-[0_20px_50px_rgba(0,0,0,0.45)]">
          <div className="flex items-center justify-between border-b border-primary/10 px-3 py-3">
            <button
              className="rounded-xl border border-primary/15 bg-zinc-950 p-2 text-primary transition hover:border-primary/30"
              onClick={() => setVisibleMonth((current) => shiftMonth(current, -1))}
              type="button"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <div className="text-sm font-medium text-white">{formatMonthLabel(visibleMonth)}</div>
            <button
              className="rounded-xl border border-primary/15 bg-zinc-950 p-2 text-primary transition hover:border-primary/30"
              onClick={() => setVisibleMonth((current) => shiftMonth(current, 1))}
              type="button"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
          <div className="grid grid-cols-7 gap-1 px-3 pb-2 pt-3">
            {["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map((day) => (
              <div key={day} className="pb-1 text-center text-[10px] uppercase tracking-[0.16em] text-zinc-500">
                {day}
              </div>
            ))}
            {weeks.flat().map((day, index) => {
              if (!day) {
                return <div key={`empty-${index}`} className="h-9" />
              }

              const time = day.getTime()
              const disabled = (minTime !== null && time < minTime) || (maxTime !== null && time > maxTime)
              const isSelected = selected ? isSameDay(day, selected) : false
              const isToday = isSameDay(day, toDateFromInput(formatDateInput(new Date())))

              return (
                <button
                  key={formatDateInput(day)}
                  className={`h-9 rounded-xl text-sm transition ${
                    disabled
                      ? "cursor-not-allowed text-zinc-700"
                      : isSelected
                        ? "bg-primary text-black"
                        : isToday
                          ? "border border-primary/35 bg-primary/10 text-primary"
                          : "text-white hover:bg-white/5"
                  }`}
                  disabled={disabled}
                  onClick={() => {
                    onChange(formatDateInput(day))
                    setOpen(false)
                  }}
                  type="button"
                >
                  {day.getDate()}
                </button>
              )
            })}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function parseDate(value: string | null) {
  if (!value) {
    return 0
  }

  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? 0 : date.getTime()
}

function parseDateStart(value: string) {
  const date = new Date(`${value}T00:00:00+03:00`)
  return Number.isNaN(date.getTime()) ? 0 : date.getTime()
}

function parseDateEnd(value: string) {
  const date = new Date(`${value}T23:59:59.999+03:00`)
  return Number.isNaN(date.getTime()) ? Number.MAX_SAFE_INTEGER : date.getTime()
}

function formatDateInput(value: Date) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, "0")
  const day = String(value.getDate()).padStart(2, "0")
  return `${year}-${month}-${day}`
}

function formatDateLabel(value: string) {
  const date = new Date(`${value}T12:00:00+03:00`)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "Europe/Moscow",
  }).format(date)
}

function toDateFromInput(value: string) {
  return new Date(`${value}T12:00:00+03:00`)
}

function monthSeed(value: string) {
  const base = value ? toDateFromInput(value) : new Date()
  return new Date(base.getFullYear(), base.getMonth(), 1, 12, 0, 0)
}

function shiftMonth(value: Date, offset: number) {
  return new Date(value.getFullYear(), value.getMonth() + offset, 1, 12, 0, 0)
}

function formatMonthLabel(value: Date) {
  return new Intl.DateTimeFormat("ru-RU", {
    month: "long",
    year: "numeric",
    timeZone: "Europe/Moscow",
  }).format(value)
}

function buildCalendarWeeks(month: Date) {
  const year = month.getFullYear()
  const monthIndex = month.getMonth()
  const firstDay = new Date(year, monthIndex, 1, 12, 0, 0)
  const daysInMonth = new Date(year, monthIndex + 1, 0, 12, 0, 0).getDate()
  const startOffset = (firstDay.getDay() + 6) % 7
  const cells: Array<Date | null> = Array.from({ length: startOffset }, () => null)

  for (let day = 1; day <= daysInMonth; day += 1) {
    cells.push(new Date(year, monthIndex, day, 12, 0, 0))
  }

  while (cells.length % 7 !== 0) {
    cells.push(null)
  }

  const weeks: Array<Array<Date | null>> = []
  for (let index = 0; index < cells.length; index += 7) {
    weeks.push(cells.slice(index, index + 7))
  }
  return weeks
}

function isSameDay(left: Date, right: Date) {
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  )
}

function buildChatLabel(chat: ChatSummary | null) {
  if (!chat) {
    return "Без названия"
  }
  if (chat.title) {
    return chat.title
  }
  if (chat.username) {
    return `@${chat.username}`
  }
  return `Чат ${chat.id}`
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

function escapeCsv(value: string) {
  if (value.includes(";") || value.includes("\n") || value.includes("\"")) {
    return `"${value.replace(/"/g, "\"\"")}"`
  }
  return value
}

function buildExportFilename(dateFrom: string, dateTo: string) {
  const today = formatDateInput(new Date())
  if (dateFrom && dateTo) {
    return `qa-report-${dateFrom}_to_${dateTo}.csv`
  }
  if (dateFrom) {
    return `qa-report-from_${dateFrom}.csv`
  }
  if (dateTo) {
    return `qa-report-until_${dateTo}.csv`
  }
  return `qa-report-${today}.csv`
}

function reportStatus(task: TaskSummary) {
  if (task.status === "done") {
    return "Done"
  }
  const fixSignals = ["review", "report", "updated"]
  const latestType = task.last_event_type ?? ""
  const latestText = (task.last_event_text ?? "").toLowerCase()
  const fixTextSignals = ["фикс", "исправил", "исправили", "пофиксил", "пофиксили", "fixed", "fix", "перезалил", "поправили"]
  const sentToFix =
    task.has_review ||
    fixSignals.includes(latestType) ||
    fixTextSignals.some((token) => latestText.includes(token))
  return sentToFix ? "Sent to Fix" : "In Progress"
}

function exportTester(assignee: string | null) {
  if (!assignee) {
    return ""
  }
  const map: Record<string, string> = {
    "Богдан": "Bogdan",
    "Глеб": "Gleb",
    "Арина": "Arina",
  }
  return map[assignee] ?? assignee
}

function buildExportTrack(task: TaskSummary) {
  if (task.chat_title) {
    const transliterated = slugifyTrackName(task.chat_title)
    if (transliterated) {
      return transliterated
    }
  }
  if (task.chat_username) {
    return slugifyTrackName(task.chat_username) || `chat_${Math.abs(task.chat_id)}`
  }
  return `chat_${Math.abs(task.chat_id)}`
}

function slugifyTrackName(value: string) {
  const transliterated = transliterateCyrillic(value)
  return transliterated
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_+/g, "_")
}

function transliterateCyrillic(value: string) {
  const map: Record<string, string> = {
    а: "a",
    б: "b",
    в: "v",
    г: "g",
    д: "d",
    е: "e",
    ё: "e",
    ж: "zh",
    з: "z",
    и: "i",
    й: "y",
    к: "k",
    л: "l",
    м: "m",
    н: "n",
    о: "o",
    п: "p",
    р: "r",
    с: "s",
    т: "t",
    у: "u",
    ф: "f",
    х: "h",
    ц: "ts",
    ч: "ch",
    ш: "sh",
    щ: "sch",
    ъ: "",
    ы: "y",
    ь: "",
    э: "e",
    ю: "yu",
    я: "ya",
  }

  return Array.from(value)
    .map((char) => {
      const lower = char.toLowerCase()
      return map[lower] ?? lower
    })
    .join("")
}

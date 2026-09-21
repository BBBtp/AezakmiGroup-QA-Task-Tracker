import { useEffect, useMemo, useRef, useState } from "react"
import { ChevronDown, Download, FileArchive, Loader2, Search } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import type { TaskSummary } from "@/types"

type Notice = { kind: "success" | "error"; text: string } | null
type DownloadInfo = {
  download_url: string
  filename: string
  bug_count: number
  run_id: number
}

export function DoqaTools({ tasks }: { tasks: TaskSummary[] }) {
  const [externalId, setExternalId] = useState("")
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<Notice>(null)
  const [download, setDownload] = useState<DownloadInfo | null>(null)
  const [suggestionsOpen, setSuggestionsOpen] = useState(false)
  const suggestionsRef = useRef<HTMLDivElement | null>(null)
  const suggestions = useMemo(
    () =>
      Array.from(new Map(tasks.map((task) => [task.task_number, task])).values()).sort(
        (left, right) => right.task_number - left.task_number,
      ),
    [tasks],
  )
  const visibleSuggestions = useMemo(() => {
    const needle = externalId.trim()
    return suggestions
      .filter((task) => !needle || String(task.task_number).includes(needle))
      .slice(0, 8)
  }, [externalId, suggestions])

  useEffect(() => {
    if (!suggestionsOpen) return

    function closeSuggestions(event: MouseEvent | TouchEvent) {
      if (!suggestionsRef.current?.contains(event.target as Node)) {
        setSuggestionsOpen(false)
      }
    }

    document.addEventListener("mousedown", closeSuggestions)
    document.addEventListener("touchstart", closeSuggestions)
    return () => {
      document.removeEventListener("mousedown", closeSuggestions)
      document.removeEventListener("touchstart", closeSuggestions)
    }
  }, [suggestionsOpen])

  async function createReport() {
    const parsedId = Number(externalId.trim())
    if (!Number.isSafeInteger(parsedId) || parsedId <= 0) {
      setNotice({ kind: "error", text: "Укажите числовой ID приложения." })
      return
    }

    setBusy(true)
    setNotice(null)
    setDownload(null)
    try {
      const response = await fetch("/api/doqa/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ external_id: parsedId }),
      })
      const result = await readReportResponse(response)
      setDownload(result)
      setNotice({
        kind: "success",
        text: `ZIP готов из прогона #${result.run_id}. Открытых багов: ${result.bug_count}. В QADB и БД задач ничего не отправлено.`,
      })
      startDownload(result)
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "Не удалось получить отчёт." })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="mx-auto grid w-full max-w-3xl gap-4">
      <Card className="border-primary/20 bg-black/80">
        <CardContent className="space-y-5 p-5 sm:p-6">
          <div className="flex items-start gap-3">
            <div className="rounded-2xl border border-primary/25 bg-primary/10 p-3 text-primary">
              <FileArchive className="h-6 w-6" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Получить ZIP из DoQA</h2>
              <p className="mt-1 text-sm leading-6 text-zinc-400">
                Укажите ID приложения. Бот найдёт самый свежий подходящий прогон и соберёт архив с открытыми багами.
              </p>
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium text-zinc-200" htmlFor="doqa-external-id">
              ID приложения
            </label>
            <div className="space-y-2" ref={suggestionsRef}>
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
                <Input
                  aria-autocomplete="list"
                  aria-controls="doqa-app-suggestions"
                  aria-expanded={suggestionsOpen}
                  autoComplete="off"
                  className="h-12 pl-10 pr-11"
                  disabled={busy}
                  id="doqa-external-id"
                  inputMode="numeric"
                  onChange={(event) => {
                    setExternalId(event.target.value.replace(/\D/g, ""))
                    setSuggestionsOpen(true)
                  }}
                  onFocus={() => setSuggestionsOpen(true)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void createReport()
                    if (event.key === "Escape") setSuggestionsOpen(false)
                  }}
                  placeholder="Например, 467"
                  role="combobox"
                  value={externalId}
                />
                <button
                  aria-label="Показать список приложений"
                  className="absolute right-1 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-xl text-zinc-400 transition hover:bg-primary/10 hover:text-primary"
                  onClick={() => setSuggestionsOpen((value) => !value)}
                  type="button"
                >
                  <ChevronDown className={`h-4 w-4 transition-transform ${suggestionsOpen ? "rotate-180" : ""}`} />
                </button>
              </div>
              {suggestionsOpen && visibleSuggestions.length ? (
                <div
                  className="max-h-60 overflow-y-auto rounded-2xl border border-primary/40 bg-zinc-950 p-1.5 shadow-2xl shadow-black/80"
                  id="doqa-app-suggestions"
                  role="listbox"
                >
                  {visibleSuggestions.map((task) => (
                    <button
                      className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition hover:bg-primary/10 focus:bg-primary/10 focus:outline-none"
                      key={task.id}
                      onClick={() => {
                        setExternalId(String(task.task_number))
                        setSuggestionsOpen(false)
                      }}
                      role="option"
                      type="button"
                    >
                      <span className="rounded-lg border border-primary/30 bg-primary/10 px-2 py-1 font-mono text-xs font-semibold text-primary">
                        ID {task.task_number}
                      </span>
                      <span className="min-w-0 truncate text-sm text-zinc-100">
                        {task.app_name || task.title}
                      </span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
            <p className="text-xs leading-5 text-zinc-500">
              Поиск идёт по пространствам: Фаст-трек, Flutter и Native.
            </p>
          </div>

          <Button className="w-full gap-2" disabled={busy} onClick={() => void createReport()}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            {busy ? "Ищу прогон и собираю ZIP..." : "Найти прогон и скачать ZIP"}
          </Button>
        </CardContent>
      </Card>

      <Card className="border-primary/20 bg-black/70">
        <CardContent className="p-4 text-sm leading-6 text-zinc-400">
          <span className="font-medium text-white">Ручной режим:</span> архив только скачивается пользователю. Такие запросы не записываются в QADB и не создают событий в базе задач.
        </CardContent>
      </Card>

      {notice ? (
        <div className={`space-y-3 rounded-2xl border px-4 py-3 text-sm ${notice.kind === "success" ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200" : "border-rose-500/30 bg-rose-500/10 text-rose-200"}`}>
          <p>{notice.text}</p>
          {download ? (
            <a
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-emerald-400 px-4 font-medium text-emerald-950 transition hover:bg-emerald-300"
              download={download.filename}
              href={download.download_url}
            >
              <Download className="h-4 w-4" />
              Скачать готовый ZIP
            </a>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}

async function readReportResponse(response: Response): Promise<DownloadInfo> {
  let payload: Partial<DownloadInfo> & { error?: string } = {}
  try {
    payload = await response.json() as Partial<DownloadInfo> & { error?: string }
  } catch {
    // The HTTP fallback below is enough when the server did not return JSON.
  }

  if (!response.ok) {
    throw new Error(payload.error || `Ошибка сервера: HTTP ${response.status}`)
  }
  if (
    typeof payload.download_url !== "string" ||
    typeof payload.filename !== "string" ||
    typeof payload.bug_count !== "number" ||
    typeof payload.run_id !== "number"
  ) {
    throw new Error("Сервер не вернул ссылку на ZIP.")
  }
  return payload as DownloadInfo
}

function startDownload(download: DownloadInfo) {
  const link = document.createElement("a")
  link.href = download.download_url
  link.download = download.filename
  document.body.appendChild(link)
  link.click()
  link.remove()
}

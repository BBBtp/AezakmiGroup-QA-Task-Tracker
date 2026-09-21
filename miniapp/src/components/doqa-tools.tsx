import { useMemo, useState } from "react"
import { Download, FileArchive, Loader2, Search } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import type { TaskSummary } from "@/types"

type Notice = { kind: "success" | "error"; text: string } | null

export function DoqaTools({ tasks }: { tasks: TaskSummary[] }) {
  const [externalId, setExternalId] = useState("")
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<Notice>(null)
  const suggestions = useMemo(
    () =>
      Array.from(new Map(tasks.map((task) => [task.task_number, task])).values()).sort(
        (left, right) => right.task_number - left.task_number,
      ),
    [tasks],
  )

  async function createReport() {
    const parsedId = Number(externalId.trim())
    if (!Number.isSafeInteger(parsedId) || parsedId <= 0) {
      setNotice({ kind: "error", text: "Укажите числовой ID приложения." })
      return
    }

    setBusy(true)
    setNotice(null)
    try {
      const response = await fetch("/api/doqa/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ external_id: parsedId }),
      })
      await downloadResponse(response, `doqa_${parsedId}.zip`)
      const bugCount = response.headers.get("X-DoQA-Bug-Count") ?? "0"
      const runId = response.headers.get("X-DoQA-Run-ID")
      setNotice({
        kind: "success",
        text: `ZIP готов${runId ? ` из прогона #${runId}` : ""}. Открытых багов: ${bugCount}. В QADB и БД задач ничего не отправлено.`,
      })
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
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
              <Input
                autoComplete="off"
                className="h-12 pl-10"
                disabled={busy}
                id="doqa-external-id"
                inputMode="numeric"
                list="doqa-app-suggestions"
                onChange={(event) => setExternalId(event.target.value.replace(/\D/g, ""))}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void createReport()
                }}
                placeholder="Например, 467"
                value={externalId}
              />
              <datalist id="doqa-app-suggestions">
                {suggestions.map((task) => (
                  <option key={task.id} value={task.task_number}>
                    {task.app_name || task.title}
                  </option>
                ))}
              </datalist>
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
        <div className={`rounded-2xl border px-4 py-3 text-sm ${notice.kind === "success" ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200" : "border-rose-500/30 bg-rose-500/10 text-rose-200"}`}>
          {notice.text}
        </div>
      ) : null}
    </section>
  )
}

async function downloadResponse(response: Response, fallbackName: string) {
  if (!response.ok) {
    let message = `Ошибка сервера: HTTP ${response.status}`
    try {
      const payload = await response.json() as { error?: string }
      if (payload.error) message = payload.error
    } catch {
      // Keep the HTTP fallback when the server did not return JSON.
    }
    throw new Error(message)
  }

  const blob = await response.blob()
  const disposition = response.headers.get("Content-Disposition") || ""
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || fallbackName
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

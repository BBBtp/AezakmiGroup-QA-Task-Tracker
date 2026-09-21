import { useRef, useState } from "react"
import { Download, FileArchive, FileUp, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
type Notice = { kind: "success" | "error"; text: string } | null

export function DoqaTools() {
  const [pdfFile, setPdfFile] = useState<File | null>(null)
  const [pdfBusy, setPdfBusy] = useState(false)
  const [notice, setNotice] = useState<Notice>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  async function parsePdf() {
    if (!pdfFile) {
      setNotice({ kind: "error", text: "Сначала выберите PDF-отчёт." })
      return
    }
    setPdfBusy(true)
    setNotice(null)
    try {
      const form = new FormData()
      form.append("file", pdfFile)
      const response = await fetch("/api/doqa/parse-pdf", { method: "POST", body: form })
      await downloadResponse(response, "doqa_parsed.zip")
      const count = response.headers.get("X-DoQA-Bug-Count") ?? "0"
      setNotice({ kind: "success", text: `ZIP готов. Открытых багов: ${count}. В QADB ничего не отправлено.` })
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "Не удалось обработать PDF." })
    } finally {
      setPdfBusy(false)
    }
  }

  return (
    <section className="mx-auto grid w-full max-w-3xl gap-4">
      <Card className="border-primary/20 bg-black/80">
        <CardContent className="space-y-5 p-5 sm:p-6">
          <div className="flex items-start gap-3">
            <div className="rounded-2xl border border-primary/25 bg-primary/10 p-3 text-primary">
              <FileUp className="h-6 w-6" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Распарсить PDF</h2>
              <p className="mt-1 text-sm leading-6 text-zinc-400">Загрузите экспорт DoQA и получите ZIP с JSON, Markdown, DOCX и вложениями.</p>
            </div>
          </div>

          <input
            ref={fileInputRef}
            accept="application/pdf,.pdf"
            className="hidden"
            onChange={(event) => setPdfFile(event.target.files?.[0] ?? null)}
            type="file"
          />
          <button
            className="flex min-h-32 w-full flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-primary/30 bg-zinc-950 px-5 py-6 text-center transition hover:border-primary/60 hover:bg-primary/5"
            onClick={() => fileInputRef.current?.click()}
            type="button"
          >
            <FileArchive className="h-7 w-7 text-primary" />
            <span className="max-w-full truncate text-sm font-medium text-white">{pdfFile?.name || "Выбрать PDF-файл"}</span>
            <span className="text-xs text-zinc-500">Лимит размера задаётся сервером</span>
          </button>
          <Button className="w-full gap-2" disabled={pdfBusy} onClick={() => void parsePdf()}>
            {pdfBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            {pdfBusy ? "Разбираю отчёт..." : "Распарсить и скачать ZIP"}
          </Button>
        </CardContent>
      </Card>

      <Card className="border-primary/20 bg-black/70">
        <CardContent className="p-4 text-sm text-zinc-400">
          <span className="font-medium text-white">Ручной режим:</span> ZIP только скачивается пользователю. Такие отчёты не записываются в QADB и не создают события в базе задач.
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
    if (response.status === 413) {
      throw new Error("PDF превышает допустимый размер либо ограничение загрузки nginx.")
    }
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

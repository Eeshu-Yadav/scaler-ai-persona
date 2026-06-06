import { useEffect, useRef, useState } from "react"
import ReactMarkdown from "react-markdown"
import {
  Bot,
  Loader2,
  Phone,
  SendHorizonal,
  Sparkles,
} from "lucide-react"

import VoiceCall from "@/VoiceCall"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000"

type Source = { source: string; title: string; score: number }
type Message = { role: "user" | "assistant"; content: string; sources?: Source[] }

const TOOL_LABELS: Record<string, string> = {
  search_background: "Searching resume & GitHub…",
  get_availability: "Checking real calendar…",
  book_meeting: "Booking the interview…",
}

const SUGGESTIONS = [
  "Why is Eeshu the right fit for an AI Engineer role?",
  "Tell me about his GSoC work at OpenWISP",
  "What's the architecture of FinMatch?",
  "Book a 30-minute interview with Eeshu",
]

export function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [busy, setBusy] = useState(false)
  const [toolStatus, setToolStatus] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, toolStatus])

  function patchLast(fn: (m: Message) => Message) {
    setMessages((prev) => {
      const next = [...prev]
      next[next.length - 1] = fn({ ...next[next.length - 1] })
      return next
    })
  }

  async function send(text?: string) {
    const content = (text ?? input).trim()
    if (!content || busy) return
    setInput("")
    setBusy(true)
    const history: Message[] = [...messages, { role: "user", content }]
    setMessages([...history, { role: "assistant", content: "", sources: [] }])

    try {
      const res = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: history.map(({ role, content }) => ({ role, content })),
        }),
      })
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const events = buffer.split("\n\n")
        buffer = events.pop() ?? ""
        for (const line of events) {
          if (!line.startsWith("data: ")) continue
          let event: { type: string; [k: string]: unknown }
          try {
            event = JSON.parse(line.slice(6))
          } catch {
            continue
          }
          if (event.type === "delta") {
            setToolStatus(null)
            patchLast((m) => ({ ...m, content: m.content + (event.text as string) }))
          } else if (event.type === "tool") {
            setToolStatus(TOOL_LABELS[event.name as string] ?? `Running ${event.name}…`)
          } else if (event.type === "sources") {
            patchLast((m) => ({ ...m, sources: event.items as Source[] }))
          } else if (event.type === "error") {
            patchLast((m) => ({
              ...m,
              content:
                m.content +
                `\n\n*Something went wrong (${event.message}). Please try again.*`,
            }))
          }
        }
      }
    } catch (err) {
      patchLast((m) => ({
        ...m,
        content:
          m.content ||
          `*Couldn't reach the backend (${err instanceof Error ? err.message : String(err)}).*`,
      }))
    } finally {
      setBusy(false)
      setToolStatus(null)
    }
  }

  return (
    <div className="bg-background text-foreground mx-auto flex h-dvh max-w-3xl flex-col">
      {/* Header */}
      <header className="border-border flex items-center gap-3 border-b px-5 py-4">
        <Avatar className="h-10 w-10">
          <AvatarFallback className="bg-primary text-primary-foreground font-semibold">
            EY
          </AvatarFallback>
        </Avatar>
        <div className="min-w-0 flex-1">
          <h1 className="text-sm font-semibold tracking-tight">
            Eeshu Yadav — AI Persona
          </h1>
          <p className="text-muted-foreground truncate text-xs">
            RAG-grounded over his real resume &amp; GitHub · books on his real
            calendar
          </p>
        </div>
        <VoiceCall />
        <a
          href="https://github.com/Eeshu-Yadav"
          target="_blank"
          rel="noreferrer"
          aria-label="Eeshu's GitHub"
          className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
        >
          GitHub
        </a>
      </header>

      {/* Messages */}
      <ScrollArea className="min-h-0 flex-1">
        <main className="flex flex-col gap-4 px-5 py-6">
          {messages.length === 0 && (
            <div className="mx-auto flex max-w-md flex-col items-center gap-5 pt-16 text-center">
              <div className="bg-primary/10 text-primary rounded-2xl p-3">
                <Bot className="h-8 w-8" />
              </div>
              <div className="space-y-2">
                <h2 className="text-lg font-semibold tracking-tight">
                  Hi, I'm Eeshu's AI representative
                </h2>
                <p className="text-muted-foreground text-sm leading-relaxed">
                  Ask about his experience, projects, and open-source work — or
                  book an interview directly. You can also{" "}
                  <span className="text-foreground inline-flex items-center gap-1 font-medium">
                    <Phone className="h-3.5 w-3.5" /> call the voice agent
                  </span>
                  .
                </p>
              </div>
              <div className="flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((s) => (
                  <Button
                    key={s}
                    variant="outline"
                    size="sm"
                    className="h-auto rounded-full px-4 py-2 text-xs font-normal whitespace-normal"
                    onClick={() => send(s)}
                  >
                    <Sparkles className="text-primary h-3 w-3" />
                    {s}
                  </Button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <div
              key={i}
              className={cn(
                "flex",
                m.role === "user" ? "justify-end" : "justify-start"
              )}
            >
              {m.role === "user" ? (
                <div className="bg-primary text-primary-foreground max-w-[80%] rounded-2xl rounded-br-md px-4 py-2.5 text-sm leading-relaxed">
                  {m.content}
                </div>
              ) : (
                <Card className="bg-card max-w-[85%] gap-0 rounded-2xl rounded-bl-md border px-4 py-3 shadow-none">
                  <div className="[&_a]:text-primary [&_code]:bg-muted [&_pre]:bg-muted max-w-none text-sm leading-relaxed [&>*+*]:mt-2 [&_code]:rounded [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_ol]:list-decimal [&_ol]:pl-5 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:p-3 [&_ul]:list-disc [&_ul]:pl-5">
                    {m.content ? (
                      <ReactMarkdown>{m.content}</ReactMarkdown>
                    ) : (
                      <span className="text-muted-foreground inline-flex items-center gap-2">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Thinking…
                      </span>
                    )}
                  </div>
                  {!!m.sources?.length && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {[...new Set(m.sources.map((s) => s.source))].map((src) => (
                        <Badge
                          key={src}
                          variant="secondary"
                          className="text-[10px] font-normal"
                        >
                          {src}
                        </Badge>
                      ))}
                    </div>
                  )}
                </Card>
              )}
            </div>
          ))}

          {toolStatus && (
            <div className="text-muted-foreground border-border bg-card inline-flex w-fit items-center gap-2 rounded-full border border-dashed px-3.5 py-1.5 text-xs">
              <Loader2 className="h-3 w-3 animate-spin" />
              {toolStatus}
            </div>
          )}
          <div ref={bottomRef} />
        </main>
      </ScrollArea>

      {/* Composer */}
      <footer className="border-border border-t px-5 py-4">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            send()
          }}
        >
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about Eeshu's background, or book an interview…"
            disabled={busy}
            autoFocus
            className="h-11 rounded-xl"
          />
          <Button
            type="submit"
            size="icon"
            disabled={busy || !input.trim()}
            className="h-11 w-11 rounded-xl"
            aria-label="Send"
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <SendHorizonal className="h-4 w-4" />
            )}
          </Button>
        </form>
        <p className="text-muted-foreground mt-2 text-center text-[11px]">
          Answers are grounded in Eeshu's actual resume and GitHub — it will say
          so when it doesn't know.
        </p>
      </footer>
    </div>
  )
}

export default App

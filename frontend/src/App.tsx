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
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"

function GithubIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden>
      <path d="M12 .5C5.73.5.5 5.73.5 12a11.5 11.5 0 0 0 7.86 10.92c.57.1.78-.25.78-.55v-2c-3.2.7-3.88-1.37-3.88-1.37-.53-1.34-1.3-1.7-1.3-1.7-1.06-.72.08-.71.08-.71 1.17.08 1.79 1.2 1.79 1.2 1.04 1.79 2.73 1.27 3.4.97.1-.75.4-1.27.73-1.56-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11 11 0 0 1 5.8 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.42-2.69 5.39-5.25 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.66.79.55A11.5 11.5 0 0 0 23.5 12C23.5 5.73 18.27.5 12 .5Z" />
    </svg>
  )
}

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
    <div className="app-bg text-foreground flex h-dvh flex-col">
      <div className="mx-auto flex h-full w-full max-w-3xl flex-col">
        {/* Header */}
        <header className="border-border/60 flex items-center gap-3 border-b px-5 py-3.5 backdrop-blur-sm">
          <div className="from-primary to-chart-2 rounded-full bg-gradient-to-br p-[1.5px]">
            <Avatar className="border-background h-9 w-9 border-2">
              <AvatarFallback className="bg-card text-foreground text-xs font-semibold">
                EY
              </AvatarFallback>
            </Avatar>
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="flex items-center gap-2 text-sm font-semibold tracking-tight">
              Eeshu Yadav
              <span className="text-muted-foreground inline-flex items-center gap-1 text-[11px] font-normal">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-70" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
                </span>
                AI Persona · live
              </span>
            </h1>
          </div>
          <VoiceCall />
          <a
            href="https://github.com/Eeshu-Yadav"
            target="_blank"
            rel="noreferrer"
            aria-label="Eeshu's GitHub"
            className={cn(buttonVariants({ variant: "ghost", size: "icon" }), "size-9 rounded-full")}
          >
            <GithubIcon className="h-4 w-4" />
          </a>
        </header>

        {/* Messages */}
        <ScrollArea className="min-h-0 flex-1">
          <main className="mx-auto flex w-full max-w-2xl flex-col gap-5 px-4 py-8">
            {messages.length === 0 && (
              <div className="anim-pop mx-auto flex max-w-lg flex-col items-center gap-6 pt-12 text-center sm:pt-20">
                <div className="from-primary/20 to-chart-2/10 text-foreground ring-border/50 rounded-2xl bg-gradient-to-br p-4 shadow-[0_8px_30px_-12px] shadow-primary/40 ring-1">
                  <Bot className="h-9 w-9" />
                </div>
                <div className="space-y-2.5">
                  <h2 className="text-2xl font-semibold tracking-tight text-balance">
                    Hi, I'm Eeshu's AI representative
                  </h2>
                  <p className="text-muted-foreground mx-auto max-w-md text-sm leading-relaxed text-pretty">
                    Ask about his experience, projects, and open-source work, or
                    book an interview on his real calendar. Prefer voice? Hit{" "}
                    <span className="text-foreground inline-flex items-center gap-1 font-medium">
                      <Phone className="h-3.5 w-3.5" /> Talk to the agent
                    </span>{" "}
                    up top, or call{" "}
                    <span className="text-foreground font-medium tabular-nums">
                      +1 270-612-3958
                    </span>
                    .
                  </p>
                </div>
                <div className="flex flex-wrap justify-center gap-2">
                  {SUGGESTIONS.map((s, i) => (
                    <button
                      key={s}
                      onClick={() => send(s)}
                      style={{ animationDelay: `${i * 60}ms` }}
                      className="anim-pop group border-border/70 bg-card/60 hover:border-primary/60 hover:bg-card inline-flex items-center gap-1.5 rounded-full border px-3.5 py-2 text-xs font-normal whitespace-normal shadow-sm transition-all hover:-translate-y-0.5 active:translate-y-0"
                    >
                      <Sparkles className="text-primary/70 group-hover:text-primary h-3 w-3 transition-colors" />
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m, i) => (
              <div
                key={i}
                className={cn(
                  "anim-msg flex",
                  m.role === "user" ? "justify-end" : "justify-start"
                )}
              >
                {m.role === "user" ? (
                  <div className="bg-primary text-primary-foreground max-w-[82%] rounded-2xl rounded-br-sm px-4 py-2.5 text-sm leading-relaxed shadow-[0_4px_14px_-6px] shadow-primary/50">
                    {m.content}
                  </div>
                ) : (
                  <div className="bg-card/80 ring-border/60 max-w-[88%] rounded-2xl rounded-bl-sm px-4 py-3 shadow-[0_2px_8px_-3px_rgba(0,0,0,0.3)] ring-1 backdrop-blur-sm">
                    <div className="[&_a]:text-primary [&_a]:underline [&_code]:bg-muted [&_pre]:bg-muted max-w-none text-sm leading-relaxed [&>*+*]:mt-2 [&_code]:rounded [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_ol]:list-decimal [&_ol]:pl-5 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:p-3 [&_ul]:list-disc [&_ul]:pl-5">
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
                      <div className="border-border/40 mt-3 flex flex-wrap items-center gap-1.5 border-t pt-2.5">
                        <span className="text-muted-foreground/70 text-[10px] uppercase tracking-wide">
                          sources
                        </span>
                        {[...new Set(m.sources.map((s) => s.source))].map((src) => (
                          <Badge
                            key={src}
                            variant="secondary"
                            className="text-[10px] font-normal tabular-nums"
                          >
                            {src}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}

            {toolStatus && (
              <div className="anim-msg text-muted-foreground border-border/60 bg-card/60 inline-flex w-fit items-center gap-2 rounded-full border px-3.5 py-1.5 text-xs backdrop-blur-sm">
                <Loader2 className="text-primary h-3 w-3 animate-spin" />
                {toolStatus}
              </div>
            )}
            <div ref={bottomRef} />
          </main>
        </ScrollArea>

        {/* Composer */}
        <footer className="border-border/60 border-t px-4 py-4">
          <form
            className="bg-card/70 focus-within:border-primary/60 focus-within:ring-primary/20 mx-auto flex max-w-2xl items-center gap-2 rounded-2xl border p-1.5 shadow-lg backdrop-blur-sm transition-all focus-within:ring-2"
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
              className="h-10 border-0 bg-transparent shadow-none focus-visible:ring-0"
            />
            <Button
              type="submit"
              size="icon"
              disabled={busy || !input.trim()}
              className="size-10 shrink-0 rounded-xl transition-transform active:scale-95"
              aria-label="Send"
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <SendHorizonal className="h-4 w-4" />
              )}
            </Button>
          </form>
        </footer>
      </div>
    </div>
  )
}

export default App

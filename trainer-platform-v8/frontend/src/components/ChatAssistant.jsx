import { useEffect, useRef, useState } from 'react'
import {
  Bot,
  Loader2,
  MessageCircle,
  Minimize2,
  Send,
  Sparkles,
  Trash2,
  User,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import api from '../utils/api'

const STORAGE_KEY = 'trainersync_assistant_messages'

const WELCOME_MESSAGE = {
  role: 'assistant',
  content:
    "Hi, I am TrainerSync Copilot. I can help with client requests, trainer pipeline stages, WhatsApp delivery, TOC generation, costs, and Sonar cleanup steps.",
}

const SYSTEM_PROMPT = `You are TrainerSync Copilot, an AI assistant built into the TrainerSync recruiter platform for Clahan Technologies.

The product currently includes:
- Client Requests and Client Threads for parsing inbound client training needs.
- Resume upload, trainer database, AI matching, shortlist, and AI Pipeline.
- Email outreach plus WhatsApp messaging through Twilio/AiSensy/Meta style providers.
- Gmail reply sync, conversation threads, Teams alerts, calendar scheduling, TOC generation, PO generation, and admin cost tracking.
- Gemini is used for chat, client extraction, reply analysis, and TOC generation. Claude/Anthropic may be used only where the backend matching/categorisation agents say so.

Answer like a practical product assistant:
- Keep replies short, direct, and operational.
- Use bullets only when they help.
- Give the next action first.
- Do not invent live data, counts, tokens, secrets, message statuses, or emails. If the user asks for actual app data, tell them which page/check to open or which sync action to run.
- Never ask for or print secrets. Tell the user to paste secrets only into Settings or environment variables.
- If the user asks about broken mail/WhatsApp/replies, mention the relevant checks: Gmail connection, provider settings, webhook/callback, logs, and thread refresh.`

const STARTERS = [
  {
    label: 'Pipeline stuck',
    prompt: 'My AI Pipeline is stuck. What should I check first?',
  },
  {
    label: 'WhatsApp status',
    prompt: 'How do I confirm whether trainer WhatsApp messages were delivered?',
  },
  {
    label: 'Client request',
    prompt: 'A client sent a training request. What should happen automatically?',
  },
  {
    label: 'TOC flow',
    prompt: 'Explain the TOC generation and confirmation flow.',
  },
]

function initialMessages() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
    return Array.isArray(saved) && saved.length ? saved : [WELCOME_MESSAGE]
  } catch {
    return [WELCOME_MESSAGE]
  }
}

function TypingDots() {
  return (
    <div className="flex items-center gap-1 px-3 py-2">
      {[0, 1, 2].map(i => (
        <span
          key={i}
          className="h-1.5 w-1.5 rounded-full bg-blue-400 animate-bounce"
          style={{ animationDelay: `${i * 130}ms` }}
        />
      ))}
    </div>
  )
}

function Message({ msg }) {
  const isUser = msg.role === 'user'
  const lines = String(msg.content || '').split('\n')

  return (
    <div className={clsx('flex gap-2.5', isUser ? 'flex-row-reverse' : 'flex-row')}>
      <div
        className={clsx(
          'mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl',
          isUser ? 'bg-blue-600 text-white' : 'bg-white text-blue-600 shadow-sm ring-1 ring-blue-100'
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>
      <div
        className={clsx(
          'max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm',
          isUser
            ? 'rounded-tr-md bg-blue-600 text-white'
            : 'rounded-tl-md border border-slate-200 bg-white text-slate-700'
        )}
      >
        {lines.map((line, index) => (
          <span key={`${line}-${index}`}>
            {line}
            {index < lines.length - 1 && <br />}
          </span>
        ))}
      </div>
    </div>
  )
}

export default function ChatAssistant() {
  const [open, setOpen] = useState(false)
  const [minimized, setMinimized] = useState(false)
  const [messages, setMessages] = useState(initialMessages)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [unread, setUnread] = useState(0)
  const [model, setModel] = useState('Gemini')
  const bottomRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(messages.slice(-30)))
  }, [messages])

  useEffect(() => {
    if (!open) return
    setUnread(0)
    window.setTimeout(() => inputRef.current?.focus(), 100)
  }, [open])

  useEffect(() => {
    if (open && !minimized) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading, open, minimized])

  const clearChat = () => {
    setMessages([WELCOME_MESSAGE])
    setInput('')
    localStorage.removeItem(STORAGE_KEY)
  }

  const send = async (text) => {
    const content = (text || input).trim()
    if (!content || loading) return

    setInput('')
    const userMessage = { role: 'user', content }
    const nextMessages = [...messages, userMessage].slice(-20)
    setMessages(nextMessages)
    setLoading(true)

    try {
      const response = await api.post('/assistant/chat', {
        system: SYSTEM_PROMPT,
        feature: 'assistant_chat',
        messages: nextMessages.map(item => ({ role: item.role, content: item.content })),
      })
      const reply = response.data?.reply || "I could not generate a response."
      setModel(response.data?.model || 'Gemini')
      setMessages(prev => [...prev, { role: 'assistant', content: reply }])
      if (!open) setUnread(count => count + 1)
    } catch (error) {
      const detail = error.response?.data?.detail
      const message = detail || 'Connection error. Check backend, Gemini API key, and network.'
      setMessages(prev => [...prev, { role: 'assistant', content: message }])
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      send()
    }
  }

  return (
    <>
      <button
        onClick={() => {
          setOpen(true)
          setMinimized(false)
        }}
        title="Open TrainerSync Copilot"
        aria-label="Open TrainerSync Copilot"
        className={clsx(
          'fixed bottom-6 right-6 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-blue-600 text-white shadow-xl shadow-blue-600/35 transition-all duration-300 hover:scale-105 hover:bg-blue-500',
          open ? 'pointer-events-none scale-90 opacity-0' : 'scale-100 opacity-100'
        )}
      >
        <MessageCircle className="h-6 w-6" />
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-red-500 px-1 text-xs font-bold text-white">
            {unread}
          </span>
        )}
      </button>

      <div
        className={clsx(
          'fixed bottom-6 right-6 z-50 w-[380px] max-w-[calc(100vw-24px)] origin-bottom-right transition-all duration-300',
          open ? 'scale-100 opacity-100' : 'pointer-events-none scale-95 opacity-0',
          minimized ? 'h-[64px]' : 'h-[560px] max-h-[calc(100vh-48px)]'
        )}
      >
        <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-slate-200 bg-slate-50 shadow-2xl">
          <div className="flex flex-shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-4 py-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-blue-600 text-white shadow-sm">
              <Sparkles className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <p className="truncate text-sm font-bold text-slate-950">TrainerSync Copilot</p>
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-700">
                  Online
                </span>
              </div>
              <p className="truncate text-xs text-slate-500">Powered by {model}</p>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={clearChat}
                className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                title="Clear chat"
                aria-label="Clear chat"
              >
                <Trash2 className="h-4 w-4" />
              </button>
              <button
                onClick={() => setMinimized(value => !value)}
                className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                title="Minimize chat"
                aria-label="Minimize chat"
              >
                <Minimize2 className="h-4 w-4" />
              </button>
              <button
                onClick={() => setOpen(false)}
                className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                title="Close chat"
                aria-label="Close chat"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {!minimized && (
            <>
              <div className="flex-1 space-y-3 overflow-y-auto p-4">
                {messages.map((msg, index) => (
                  <Message key={`${msg.role}-${index}`} msg={msg} />
                ))}
                {loading && (
                  <div className="flex gap-2.5">
                    <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl bg-white text-blue-600 shadow-sm ring-1 ring-blue-100">
                      <Bot className="h-4 w-4" />
                    </div>
                    <div className="rounded-2xl rounded-tl-md border border-slate-200 bg-white shadow-sm">
                      <TypingDots />
                    </div>
                  </div>
                )}
                <div ref={bottomRef} />
              </div>

              {messages.length === 1 && (
                <div className="border-t border-slate-200 bg-white px-4 py-3">
                  <p className="mb-2 text-[11px] font-bold uppercase tracking-wide text-slate-400">
                    Quick help
                  </p>
                  <div className="grid grid-cols-2 gap-2">
                    {STARTERS.map(item => (
                      <button
                        key={item.label}
                        onClick={() => send(item.prompt)}
                        className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-left text-xs font-semibold text-slate-600 transition-all hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700"
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex-shrink-0 border-t border-slate-200 bg-white p-3">
                <div className="flex gap-2 rounded-2xl border border-slate-200 bg-slate-50 p-1.5 focus-within:border-blue-300 focus-within:bg-white">
                  <textarea
                    ref={inputRef}
                    value={input}
                    onChange={event => setInput(event.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Ask about pipeline, WhatsApp, client requests..."
                    rows={1}
                    className="max-h-24 min-h-9 flex-1 resize-none bg-transparent px-2 py-2 text-sm text-slate-800 placeholder-slate-400 focus:outline-none"
                  />
                  <button
                    onClick={() => send()}
                    disabled={!input.trim() || loading}
                    className={clsx(
                      'flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl transition-all',
                      input.trim() && !loading
                        ? 'bg-blue-600 text-white hover:bg-blue-700'
                        : 'bg-slate-200 text-slate-400'
                    )}
                    aria-label="Send message"
                  >
                    {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  </button>
                </div>
                <p className="mt-2 text-center text-[10px] font-medium text-slate-400">
                  Copilot gives guidance. Check app pages for live records.
                </p>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  )
}

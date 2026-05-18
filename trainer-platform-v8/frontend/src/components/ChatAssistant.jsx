import { useState, useRef, useEffect } from 'react'
import { MessageCircle, X, Send, Bot, User, Sparkles, Minimize2, Trash2 } from 'lucide-react'
import clsx from 'clsx'
import api from '../utils/api'

const SYSTEM_PROMPT = `You are TrainerSync Assistant — a helpful AI built into the TrainerSync recruiter platform.
You help recruiters with:
- Finding and matching trainers to requirements
- Understanding email outreach status and reply analytics
- Explaining dashboard stats and metrics
- Advising on follow-up strategies and retry schedules
- General guidance on trainer recruitment best practices

Keep responses concise, practical, and actionable. Use bullet points for lists. 
Be friendly but professional. If asked about platform features, explain them clearly.
Don't make up specific data — if asked about their actual data, tell them to check the relevant page.`

const SUGGESTIONS = [
  'How do I find trainers for a requirement?',
  'Explain the retry follow-up settings',
  'How does the email matching work?',
  'What does the match score mean?',
]

function TypingDots() {
  return (
    <div className="flex items-center gap-1 px-4 py-3">
      {[0, 1, 2].map(i => (
        <span key={i} className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce"
          style={{ animationDelay: `${i * 150}ms` }} />
      ))}
    </div>
  )
}

function Message({ msg }) {
  const isUser = msg.role === 'user'
  return (
    <div className={clsx('flex gap-2.5 mb-4', isUser ? 'flex-row-reverse' : 'flex-row')}>
      <div className={clsx(
        'w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5',
        isUser ? 'bg-blue-600' : 'bg-slate-800'
      )}>
        {isUser ? <User className="w-3.5 h-3.5 text-white" /> : <Bot className="w-3.5 h-3.5 text-blue-400" />}
      </div>
      <div className={clsx(
        'max-w-[78%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed',
        isUser
          ? 'bg-blue-600 text-white rounded-tr-sm'
          : 'bg-slate-800/80 text-slate-200 rounded-tl-sm'
      )}>
        {msg.content.split('\n').map((line, i) => (
          <span key={i}>{line}{i < msg.content.split('\n').length - 1 && <br />}</span>
        ))}
      </div>
    </div>
  )
}

export default function ChatAssistant() {
  const [open, setOpen] = useState(false)
  const [minimized, setMinimized] = useState(false)
  const [messages, setMessages] = useState([
    { role: 'assistant', content: "Hi! I'm your TrainerSync assistant 👋\nAsk me anything about the platform, trainer matching, or email outreach." }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [unread, setUnread] = useState(0)
  const bottomRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    if (open) { setUnread(0); setTimeout(() => inputRef.current?.focus(), 100) }
  }, [open])

  useEffect(() => {
    if (open && !minimized) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading, open, minimized])

  const send = async (text) => {
    const content = (text || input).trim()
    if (!content || loading) return
    setInput('')
    const userMsg = { role: 'user', content }
    const newMessages = [...messages, userMsg]
    setMessages(newMessages)
    setLoading(true)

    try {
      const response = await api.post('/assistant/chat', {
        system: SYSTEM_PROMPT,
        messages: newMessages.map(m => ({ role: m.role, content: m.content })),
      })
      const reply = response.data?.reply || "Sorry, I couldn't get a response."
      setMessages(prev => [...prev, { role: 'assistant', content: reply }])
      if (!open) setUnread(n => n + 1)
    } catch (err) {
      setMessages(prev => [...prev, { role: 'assistant', content: '⚠️ Connection error. Please try again.' }])
    }
    setLoading(false)
  }

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  return (
    <>
      {/* Floating button */}
      <button
        onClick={() => { setOpen(true); setMinimized(false) }}
        title="Open TrainerSync AI assistant"
        aria-label="Open TrainerSync AI assistant"
        className={clsx(
          'fixed bottom-6 right-6 z-50 w-14 h-14 bg-blue-600 rounded-full shadow-xl shadow-blue-600/40',
          'flex items-center justify-center transition-all duration-300 hover:scale-110 hover:bg-blue-500',
          open ? 'scale-0 opacity-0 pointer-events-none' : 'scale-100 opacity-100'
        )}>
        <MessageCircle className="w-6 h-6 text-white" />
        {unread > 0 && (
          <span className="absolute -top-1 -right-1 w-5 h-5 bg-red-500 rounded-full text-xs text-white font-bold flex items-center justify-center">
            {unread}
          </span>
        )}
      </button>

      {/* Chat window */}
      <div className={clsx(
        'fixed bottom-6 right-6 z-50 w-[360px] transition-all duration-300 origin-bottom-right',
        open ? 'scale-100 opacity-100' : 'scale-95 opacity-0 pointer-events-none',
        minimized ? 'h-14' : 'h-[520px]'
      )}>
        <div className="flex flex-col h-full bg-slate-900 border border-slate-700/50 rounded-2xl shadow-2xl overflow-hidden">
          {/* Header */}
          <div className="flex items-center gap-3 px-4 py-3 bg-slate-800/80 border-b border-slate-700/50 flex-shrink-0">
            <div className="w-8 h-8 bg-blue-600 rounded-xl flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-white">TrainerSync AI</p>
              <p className="text-xs text-emerald-400 flex items-center gap-1">
                <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" />
                Online
              </p>
            </div>
            <div className="flex items-center gap-1">
              <button onClick={() => { setMessages(msgs => [msgs[0]]); }}
                className="p-1.5 hover:bg-slate-700 rounded-lg text-slate-400 hover:text-slate-200 transition-colors" title="Clear chat">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
              <button onClick={() => setMinimized(!minimized)}
                className="p-1.5 hover:bg-slate-700 rounded-lg text-slate-400 hover:text-slate-200 transition-colors">
                <Minimize2 className="w-3.5 h-3.5" />
              </button>
              <button onClick={() => setOpen(false)}
                className="p-1.5 hover:bg-slate-700 rounded-lg text-slate-400 hover:text-slate-200 transition-colors">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {!minimized && (
            <>
              {/* Messages */}
              <div className="flex-1 overflow-y-auto p-4 space-y-1 scrollbar-thin">
                {messages.map((msg, i) => <Message key={i} msg={msg} />)}
                {loading && (
                  <div className="flex gap-2.5">
                    <div className="w-7 h-7 rounded-full bg-slate-800 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <Bot className="w-3.5 h-3.5 text-blue-400" />
                    </div>
                    <div className="bg-slate-800/80 rounded-2xl rounded-tl-sm">
                      <TypingDots />
                    </div>
                  </div>
                )}
                <div ref={bottomRef} />
              </div>

              {/* Suggestions — only when 1 message */}
              {messages.length === 1 && (
                <div className="px-4 pb-3 flex flex-wrap gap-1.5">
                  {SUGGESTIONS.map(s => (
                    <button key={s} onClick={() => send(s)}
                      className="text-xs px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-full border border-slate-700/50 transition-all">
                      {s}
                    </button>
                  ))}
                </div>
              )}

              {/* Input */}
              <div className="px-3 pb-3 flex-shrink-0">
                <div className="flex gap-2 bg-slate-800 border border-slate-700/50 rounded-xl p-1.5">
                  <textarea
                    ref={inputRef}
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={handleKey}
                    placeholder="Ask me anything..."
                    rows={1}
                    className="flex-1 bg-transparent text-sm text-white placeholder-slate-500 resize-none focus:outline-none px-2 py-1 max-h-24"
                    style={{ minHeight: '32px' }}
                  />
                  <button onClick={() => send()}
                    disabled={!input.trim() || loading}
                    className={clsx(
                      'w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 transition-all self-end',
                      input.trim() && !loading
                        ? 'bg-blue-600 text-white hover:bg-blue-500'
                        : 'bg-slate-700 text-slate-500'
                    )}>
                    <Send className="w-3.5 h-3.5" />
                  </button>
                </div>
                <p className="text-center text-slate-600 text-[10px] mt-1.5">Powered by Claude AI</p>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  )
}

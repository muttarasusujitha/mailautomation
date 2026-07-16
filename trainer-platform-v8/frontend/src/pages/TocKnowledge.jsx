import { useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import {
  BookOpen,
  Check,
  Database,
  Edit3,
  Layers,
  Plus,
  RefreshCw,
  Save,
  Trash2,
  Upload,
} from 'lucide-react'
import { deleteTocKnowledge, getTocKnowledge, importTocKnowledge, saveTocKnowledge } from '../utils/api'

const LEVELS = ['foundation', 'core', 'advanced', 'observability', 'security', 'projects', 'revision', 'capstone']

const emptyDomain = () => ({
  key: '',
  name: '',
  icon: 'book',
  aliasesText: '',
  active: true,
  level_map: Object.fromEntries(LEVELS.map(level => [level, []])),
  jiraDailyText: 'Update sprint board\nLog time\nMove cards',
  jiraWeeklyText: 'Sprint review\nRetrospective',
  certificationsText: '',
})

function lines(value) {
  return String(value || '').split('\n').map(item => item.trim()).filter(Boolean)
}

function csv(value) {
  return String(value || '').split(',').map(item => item.trim()).filter(Boolean)
}

function toForm(doc) {
  const source = doc.level_map ? doc : { ...doc, ...(doc.toc || {}) }
  const levelMap = Object.fromEntries(LEVELS.map(level => [level, [...((source.level_map || {})[level] || [])]]))
  return {
    ...emptyDomain(),
    ...source,
    key: source.key || doc.key || doc.domain || '',
    name: source.name || doc.name || doc.domain || '',
    level_map: levelMap,
    aliasesText: (source.aliases || []).join(', '),
    jiraDailyText: ((source.jira_practice || {}).daily || []).join('\n'),
    jiraWeeklyText: ((source.jira_practice || {}).weekly || []).join('\n'),
    certificationsText: (source.certifications || []).join('\n'),
  }
}

function toPayload(form) {
  const key = form.key || form.name
  const toc = {
    name: form.name,
    key,
    icon: form.icon || 'book',
    aliases: csv(form.aliasesText),
    active: form.active,
    level_map: form.level_map,
    jira_practice: {
      daily: lines(form.jiraDailyText),
      weekly: lines(form.jiraWeeklyText),
    },
    certifications: lines(form.certificationsText),
  }

  return {
    ...toc,
    domain: key,
    toc,
  }
}

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">{label}</span>
      {children}
    </label>
  )
}

function Input(props) {
  return <input {...props} className={`h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none transition focus:border-cyan-500 focus:ring-4 focus:ring-cyan-100 ${props.className || ''}`} />
}

function Textarea(props) {
  return <textarea {...props} className={`min-h-24 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-cyan-500 focus:ring-4 focus:ring-cyan-100 ${props.className || ''}`} />
}

function topicCount(domain) {
  return LEVELS.reduce((total, level) => total + ((domain.level_map || {})[level] || []).length, 0)
}

export default function TocKnowledge() {
  const [domains, setDomains] = useState([])
  const [selectedKey, setSelectedKey] = useState('')
  const [form, setForm] = useState(emptyDomain)
  const [level, setLevel] = useState('foundation')
  const [topicDraft, setTopicDraft] = useState({ topic: '', subtopicsText: '', toolsText: '', lab: '' })
  const [importText, setImportText] = useState('')
  const [importing, setImporting] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const selected = useMemo(() => domains.find(item => item.key === selectedKey), [domains, selectedKey])

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await getTocKnowledge()
      const list = data.domains || data.items || []
      setDomains(list)
      if (!selectedKey && list[0]) {
        setSelectedKey(list[0].key)
        setForm(toForm(list[0]))
      }
    } catch (error) {
      toast.error(error.message || 'Could not load ToC knowledge')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  useEffect(() => {
    if (selected) setForm(toForm(selected))
  }, [selectedKey])

  const startNew = () => {
    setSelectedKey('')
    setForm(emptyDomain())
    setLevel('foundation')
  }

  const updateForm = (patch) => setForm(current => ({ ...current, ...patch }))

  const addTopic = () => {
    const topic = topicDraft.topic.trim()
    if (!topic) return toast.error('Topic name is required')
    const nextTopic = {
      topic,
      subtopics: lines(topicDraft.subtopicsText),
      tools: csv(topicDraft.toolsText),
      lab: topicDraft.lab.trim(),
    }
    setForm(current => ({
      ...current,
      level_map: {
        ...current.level_map,
        [level]: [...(current.level_map[level] || []), nextTopic],
      },
    }))
    setTopicDraft({ topic: '', subtopicsText: '', toolsText: '', lab: '' })
  }

  const removeTopic = (targetLevel, index) => {
    setForm(current => ({
      ...current,
      level_map: {
        ...current.level_map,
        [targetLevel]: (current.level_map[targetLevel] || []).filter((_, idx) => idx !== index),
      },
    }))
  }

  const save = async () => {
    if (!form.name.trim()) return toast.error('Domain name is required')
    if (!topicCount(form)) return toast.error('Add at least one topic')
    setSaving(true)
    try {
      const { data } = await saveTocKnowledge(toPayload(form))
      const savedDomain = typeof data.domain === 'object' ? data.domain : { ...toPayload(form), domain: data.domain || form.key || form.name }
      toast.success('ToC knowledge saved')
      await load()
      setSelectedKey(savedDomain.key || savedDomain.domain)
      setForm(toForm(savedDomain))
    } catch (error) {
      toast.error(error.message || 'Could not save domain')
    } finally {
      setSaving(false)
    }
  }

  const removeDomain = async () => {
    if (!form.key) return
    if (!window.confirm(`Delete ${form.name}?`)) return
    try {
      await deleteTocKnowledge(form.key)
      toast.success('Domain deleted')
      startNew()
      await load()
    } catch (error) {
      toast.error(error.message || 'Could not delete domain')
    }
  }

  const importKnowledge = async () => {
    if (!importText.trim()) return toast.error('Paste technology knowledge text first')
    setImporting(true)
    try {
      const { data } = await importTocKnowledge(importText)
      toast.success(`Imported ${data.imported || 0} technology domains`)
      setImportText('')
      await load()
      if ((data.domains || [])[0]) {
        setSelectedKey(data.domains[0].key)
        setForm(toForm(data.domains[0]))
      }
    } catch (error) {
      toast.error(error.message || 'Could not import knowledge')
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Database className="h-6 w-6 text-blue-600" /> ToC Knowledge Base
          </h1>
          <p className="mt-1 text-sm text-slate-500">Manage technology curricula used by the automated ToC generator.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={load} className="btn-secondary inline-flex items-center gap-2" disabled={loading}>
            <RefreshCw className="h-4 w-4" /> Refresh
          </button>
          <button onClick={startNew} className="btn-primary inline-flex items-center gap-2">
            <Plus className="h-4 w-4" /> New Domain
          </button>
        </div>
      </div>

      <div className="rounded-lg border border-blue-100 bg-white p-4 shadow-sm">
        <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="flex items-center gap-2 text-base font-bold text-slate-950">
              <Upload className="h-4 w-4 text-blue-600" /> Import Detailed Subtopics
            </h2>
            <p className="mt-1 text-sm text-slate-500">Paste blocks with Technology Name, Aliases, Foundation/Core/Advanced Topics, Tools, Labs, and Certifications.</p>
          </div>
          <button type="button" onClick={importKnowledge} disabled={importing} className="btn-primary inline-flex items-center gap-2">
            {importing ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            Import
          </button>
        </div>
        <Textarea
          value={importText}
          onChange={event => setImportText(event.target.value)}
          className="min-h-40 font-mono"
          placeholder={'Technology Name: JavaScript\nAliases: js, javascript\n\nFoundation Topics:\n1. Variables and Data Types\n   - var, let, const differences\n   - Primitive types\n\nTools:\n- VS Code\n- Chrome DevTools'}
        />
      </div>

      <div className="grid gap-5 xl:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-sm font-bold text-slate-900">Admin Domains</p>
            <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-bold text-blue-700">{domains.length}</span>
          </div>
          <div className="space-y-2">
            {domains.map(domain => (
              <button
                key={domain.key}
                type="button"
                onClick={() => setSelectedKey(domain.key)}
                className={`w-full rounded-lg border px-3 py-3 text-left transition ${selectedKey === domain.key ? 'border-cyan-300 bg-blue-50' : 'border-slate-200 bg-white hover:bg-slate-50'}`}
              >
                <div className="flex items-center gap-2">
                  <BookOpen className="h-4 w-4 text-blue-600" />
                  <span className="min-w-0 flex-1 truncate text-sm font-bold text-slate-900">{domain.name}</span>
                  <span className="text-xs font-semibold text-slate-400">{topicCount(domain)}</span>
                </div>
                <p className="mt-1 truncate text-xs text-slate-500">{domain.key}</p>
              </button>
            ))}
            {!domains.length && !loading && (
              <div className="rounded-lg border border-dashed border-slate-200 p-4 text-center text-sm text-slate-500">
                No admin domains yet.
              </div>
            )}
          </div>
        </aside>

        <section className="space-y-5">
          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-base font-bold text-slate-950">
                <Edit3 className="h-4 w-4 text-blue-600" /> Domain Details
              </h2>
              <label className="flex items-center gap-2 text-sm font-semibold text-slate-600">
                <input type="checkbox" checked={form.active} onChange={event => updateForm({ active: event.target.checked })} />
                Active
              </label>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <Field label="Domain Name">
                <Input value={form.name} onChange={event => updateForm({ name: event.target.value })} placeholder="Rust Programming" />
              </Field>
              <Field label="Key">
                <Input value={form.key} onChange={event => updateForm({ key: event.target.value })} placeholder="rust_programming" />
              </Field>
              <Field label="Aliases">
                <Input value={form.aliasesText} onChange={event => updateForm({ aliasesText: event.target.value })} placeholder="rust, systems programming" />
              </Field>
            </div>
            <div className="mt-4 grid gap-4 md:grid-cols-3">
              <Field label="Daily Jira Practice">
                <Textarea value={form.jiraDailyText} onChange={event => updateForm({ jiraDailyText: event.target.value })} />
              </Field>
              <Field label="Weekly Jira Practice">
                <Textarea value={form.jiraWeeklyText} onChange={event => updateForm({ jiraWeeklyText: event.target.value })} />
              </Field>
              <Field label="Certifications">
                <Textarea value={form.certificationsText} onChange={event => updateForm({ certificationsText: event.target.value })} placeholder="One certification per line" />
              </Field>
            </div>
          </div>

          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <h2 className="flex items-center gap-2 text-base font-bold text-slate-950">
                <Layers className="h-4 w-4 text-blue-600" /> Curriculum Topics
              </h2>
              <div className="flex flex-wrap gap-2">
                {LEVELS.map(item => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => setLevel(item)}
                    className={`rounded-lg px-3 py-1.5 text-xs font-bold capitalize transition ${level === item ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}
                  >
                    {item} ({(form.level_map[item] || []).length})
                  </button>
                ))}
              </div>
            </div>

            <div className="grid gap-3 lg:grid-cols-[1fr_1fr_1fr]">
              <Field label="Topic">
                <Input value={topicDraft.topic} onChange={event => setTopicDraft({ ...topicDraft, topic: event.target.value })} placeholder="Ownership and Borrowing" />
              </Field>
              <Field label="Tools">
                <Input value={topicDraft.toolsText} onChange={event => setTopicDraft({ ...topicDraft, toolsText: event.target.value })} placeholder="Rust, Cargo, VS Code" />
              </Field>
              <Field label="Lab">
                <Input value={topicDraft.lab} onChange={event => setTopicDraft({ ...topicDraft, lab: event.target.value })} placeholder="Build CLI parser" />
              </Field>
            </div>
            <div className="mt-3 grid gap-3 lg:grid-cols-[1fr_auto]">
              <Field label="Subtopics">
                <Textarea value={topicDraft.subtopicsText} onChange={event => setTopicDraft({ ...topicDraft, subtopicsText: event.target.value })} placeholder="One subtopic per line" />
              </Field>
              <div className="flex items-end">
                <button type="button" onClick={addTopic} className="btn-primary inline-flex h-10 items-center gap-2">
                  <Plus className="h-4 w-4" /> Add Topic
                </button>
              </div>
            </div>

            <div className="mt-5 space-y-3">
              {LEVELS.map(item => (form.level_map[item] || []).length > 0 && (
                <div key={item} className="rounded-lg border border-slate-200">
                  <div className="border-b border-slate-100 bg-slate-50 px-3 py-2 text-xs font-bold uppercase tracking-wide text-slate-500">{item}</div>
                  <div className="divide-y divide-slate-100">
                    {(form.level_map[item] || []).map((topic, index) => (
                      <div key={`${item}-${index}`} className="flex gap-3 px-3 py-3">
                        <div className="min-w-0 flex-1">
                          <p className="font-bold text-slate-950">{topic.topic}</p>
                          <p className="mt-1 text-xs text-slate-500">{(topic.subtopics || []).join(', ')}</p>
                          <p className="mt-1 text-xs font-semibold text-blue-700">{(topic.tools || []).join(' + ')}</p>
                          {topic.lab && <p className="mt-1 text-xs text-slate-600">Lab: {topic.lab}</p>}
                        </div>
                        <button type="button" onClick={() => removeTopic(item, index)} className="h-9 rounded-lg border border-rose-100 px-2 text-rose-600 hover:bg-rose-50" aria-label="Remove topic">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="flex justify-end gap-2">
            {form.key && (
              <button type="button" onClick={removeDomain} className="btn-secondary inline-flex items-center gap-2 text-rose-600">
                <Trash2 className="h-4 w-4" /> Delete
              </button>
            )}
            <button type="button" onClick={save} disabled={saving} className="btn-primary inline-flex items-center gap-2">
              {saving ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Save Knowledge
            </button>
          </div>

          <div className="rounded-lg border border-emerald-100 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            <Check className="mr-2 inline h-4 w-4" />
            Saved domains are used automatically by the ToC generator when the client technology matches the key, name, or aliases.
          </div>
        </section>
      </div>
    </div>
  )
}

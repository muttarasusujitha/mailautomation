import { useEffect, useMemo, useState } from 'react'
import { Check, Moon, Palette, Sparkles, Sun } from 'lucide-react'
import clsx from 'clsx'

const STORAGE_THEME = 'ts_theme'
const STORAGE_PLATE = 'ts_theme_plate'
const STORAGE_GLOW = 'ts_theme_glow'
const STORAGE_GLOW_COLOR = 'ts_theme_glow_color'

function plateSurface(id, index) {
  if (id === 'plain-white') return '#ffffff'
  if (index >= 22) return '#e4f2ff'
  if (index >= 19) return '#edf7ff'
  if (index >= 13) return '#eef6fb'
  if (index >= 9) return '#eaf8fb'
  return '#edf5ff'
}

function plateBorder(id, index) {
  if (id === 'plain-white') return '#e2e8f0'
  if (index >= 22) return '#c6ddf4'
  if (index >= 13) return '#d5e6f2'
  return '#d8e6f5'
}

const PLATES = [
  ['plain-white', 'Plain White', '#ffffff', '#ffffff', '#ffffff', '100,116,139', '148,163,184'],
  ['ice-blue', 'Ice Blue', '#f6fbff', '#eef8ff', '#e8f5ff', '14,165,233', '20,184,166'],
  ['soft-sky', 'Soft Sky', '#eef8ff', '#e7f4ff', '#dff0fb', '14,165,233', '59,130,246'],
  ['cloud-blue', 'Cloud Blue', '#e8f5ff', '#e1f1fb', '#d8edf8', '2,132,199', '20,184,166'],
  ['powder-blue', 'Powder Blue', '#e1f1fb', '#d8edf8', '#d1e8f5', '14,116,144', '59,130,246'],
  ['mist-blue', 'Mist Blue', '#dff2fb', '#d7ecf8', '#cfe7f4', '6,182,212', '14,165,233'],
  ['cool-blue', 'Cool Blue', '#d7ecf8', '#cfe7f4', '#c7e2f0', '14,165,233', '99,102,241'],
  ['blue-frost', 'Blue Frost', '#f3fbff', '#ebf8fb', '#e3f4f8', '56,189,248', '20,184,166'],
  ['aqua-mist', 'Aqua Mist', '#eaf8fb', '#e1f4f7', '#d8eff3', '6,182,212', '45,212,191'],
  ['mint-air', 'Mint Air', '#e6f7f2', '#def4ef', '#d6eee9', '20,184,166', '14,165,233'],
  ['seafoam-light', 'Seafoam Light', '#def4ef', '#d6eee9', '#cfe9e4', '20,184,166', '16,185,129'],
  ['aqua-plate', 'Aqua Plate', '#d8f0ee', '#d0ebe9', '#c8e5e3', '13,148,136', '14,165,233'],
  ['fresh-mint', 'Fresh Mint', '#edfdf7', '#e3f8f0', '#daf2e9', '16,185,129', '14,165,233'],
  ['slate-white', 'Slate White', '#f8fafc', '#f1f7fb', '#eaf1f6', '100,116,139', '14,165,233'],
  ['office-blue', 'Office Blue', '#f1f7fb', '#eaf3f8', '#e1eef5', '14,165,233', '100,116,139'],
  ['clean-desk', 'Clean Desk', '#eef6fb', '#e6f0f7', '#dfeaf3', '59,130,246', '14,165,233'],
  ['soft-admin', 'Soft Admin', '#eaf3f8', '#e3eef5', '#dbe8f1', '100,116,139', '20,184,166'],
  ['calm-work', 'Calm Work', '#e6f0f7', '#ddebf5', '#d4e5f0', '14,116,144', '59,130,246'],
  ['enterprise-blue', 'Enterprise Blue', '#ddebf5', '#d4e5f0', '#cbdfea', '37,99,235', '14,116,144'],
  ['glass-blue', 'Glass Blue', '#f5fbff', '#edf7ff', '#e5f2fb', '14,165,233', '20,184,166'],
  ['premium-sky', 'Premium Sky', '#edf7ff', '#e7f3ff', '#dfedfb', '59,130,246', '14,165,233'],
  ['bright-plate', 'Bright Plate', '#e7f3ff', '#e1effd', '#d9e9f8', '14,165,233', '37,99,235'],
  ['active-pale-blue', 'Active Pale Blue', '#e4f2ff', '#dceeff', '#d5e8fa', '14,165,233', '20,184,166'],
  ['deep-pale-blue', 'Deep Pale Blue', '#dceeff', '#d6eaff', '#cfe4fb', '37,99,235', '6,182,212'],
  ['stronger-blue', 'Stronger Blue', '#d6eaff', '#cfe4fb', '#c7ddf5', '37,99,235', '14,116,144'],
].map(([id, name, start, mid, end, accent, accent2], index) => ({
  id,
  name,
  number: index + 1,
  start,
  mid,
  end,
  accent,
  accent2,
  surface: plateSurface(id, index),
  soft: id === 'plain-white' ? '#f8fafc' : mid,
  border: plateBorder(id, index),
}))

const GLOWS = [
  ['soft', 'Soft', '12px', '30px', '0.12', '28px', '0.08', '16px', '40px', '0.14', '32px', '0.08'],
  ['clean', 'Clean', '8px', '22px', '0.09', '20px', '0.06', '12px', '30px', '0.10', '24px', '0.06'],
  ['wide', 'Wide', '16px', '46px', '0.12', '46px', '0.10', '20px', '58px', '0.14', '52px', '0.10'],
  ['bright', 'Bright', '12px', '34px', '0.18', '30px', '0.10', '18px', '46px', '0.20', '36px', '0.11'],
  ['aqua', 'Aqua', '10px', '28px', '0.10', '42px', '0.14', '14px', '38px', '0.11', '48px', '0.15'],
  ['blue', 'Blue', '14px', '36px', '0.16', '18px', '0.04', '18px', '48px', '0.18', '22px', '0.05'],
  ['strong', 'Strong', '18px', '48px', '0.22', '42px', '0.14', '24px', '64px', '0.24', '48px', '0.15'],
  ['none', 'None', '0px', '0px', '0', '0px', '0', '0px', '0px', '0', '0px', '0'],
].map(([id, name, panelY, panelBlur, panelAlpha, panelSpread, panelSoftAlpha, cardY, cardBlur, cardAlpha, cardSpread, cardSoftAlpha], index) => ({
  id,
  name,
  number: index + 1,
  panelY,
  panelBlur,
  panelAlpha,
  panelSpread,
  panelSoftAlpha,
  cardY,
  cardBlur,
  cardAlpha,
  cardSpread,
  cardSoftAlpha,
}))

const GLOW_COLORS = [
  ['plate', 'Theme Match', '', ''],
  ['brand-blue', 'Brand Blue', '37,99,235', '29,78,216'],
  ['deep-brand', 'Deep Brand', '30,64,175', '37,99,235'],
  ['client-blue', 'Client Blue', '37,99,235', '6,182,212'],
  ['pipeline-cyan', 'Pipeline Cyan', '6,182,212', '14,165,233'],
  ['toc-teal', 'TOC Teal', '13,148,136', '20,184,166'],
  ['success-emerald', 'Success Green', '16,185,129', '5,150,105'],
  ['ai-violet', 'AI Violet', '139,92,246', '124,58,237'],
  ['invoice-cyan', 'Invoice Cyan', '8,145,178', '6,182,212'],
  ['warning-amber', 'Warning Amber', '245,158,11', '217,119,6'],
  ['soft-brand', 'Soft Brand', '96,165,250', '186,230,253'],
  ['ops-mix', 'Ops Mix', '37,99,235', '16,185,129'],
].map(([id, name, color, color2], index) => ({
  id,
  name,
  number: index + 1,
  color,
  color2,
}))

function applyPlate(plateId) {
  const plate = PLATES.find(item => item.id === plateId) || PLATES[0]
  const root = document.documentElement
  root.style.setProperty('--app-bg-start', plate.start)
  root.style.setProperty('--app-bg-mid', plate.mid)
  root.style.setProperty('--app-bg-end', plate.end)
  root.style.setProperty('--app-bg-accent', plate.accent)
  root.style.setProperty('--app-bg-accent-2', plate.accent2)
  root.style.setProperty('--app-surface', plate.surface)
  root.style.setProperty('--app-surface-soft', plate.soft)
  root.style.setProperty('--app-surface-border', plate.border)
}

function applyGlow(glowId) {
  const glow = GLOWS.find(item => item.id === glowId) || GLOWS[0]
  const root = document.documentElement
  root.style.setProperty('--linkedin-glow-panel-y', glow.panelY)
  root.style.setProperty('--linkedin-glow-panel-blur', glow.panelBlur)
  root.style.setProperty('--linkedin-glow-panel-alpha', glow.panelAlpha)
  root.style.setProperty('--linkedin-glow-panel-spread', glow.panelSpread)
  root.style.setProperty('--linkedin-glow-panel-soft-alpha', glow.panelSoftAlpha)
  root.style.setProperty('--linkedin-glow-card-y', glow.cardY)
  root.style.setProperty('--linkedin-glow-card-blur', glow.cardBlur)
  root.style.setProperty('--linkedin-glow-card-alpha', glow.cardAlpha)
  root.style.setProperty('--linkedin-glow-card-spread', glow.cardSpread)
  root.style.setProperty('--linkedin-glow-card-soft-alpha', glow.cardSoftAlpha)
}

function applyGlowColor(colorId, plateId) {
  const plate = PLATES.find(item => item.id === plateId) || PLATES[0]
  const color = GLOW_COLORS.find(item => item.id === colorId) || GLOW_COLORS[0]
  const root = document.documentElement
  root.style.setProperty('--linkedin-glow-color', color.color || plate.accent)
  root.style.setProperty('--linkedin-glow-color-2', color.color2 || plate.accent2)
}

export default function ThemeToggle({ floating = false }) {
  const [theme, setTheme] = useState(() => localStorage.getItem(STORAGE_THEME) || 'light')
  const [plate, setPlate] = useState('plain-white')
  const [glow, setGlow] = useState('none')
  const [glowColor, setGlowColor] = useState('plate')
  const [open, setOpen] = useState(false)
  const selectedPlate = useMemo(() => PLATES.find(item => item.id === plate) || PLATES[0], [plate])
  const selectedGlow = useMemo(() => GLOWS.find(item => item.id === glow) || GLOWS[0], [glow])
  const selectedGlowColor = useMemo(() => GLOW_COLORS.find(item => item.id === glowColor) || GLOW_COLORS[0], [glowColor])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem(STORAGE_THEME, theme)
    globalThis.dispatchEvent(new CustomEvent('ts-theme-change', { detail: { theme } }))
  }, [theme])

  useEffect(() => {
    applyPlate(plate)
    applyGlowColor(glowColor, plate)
    localStorage.setItem(STORAGE_PLATE, plate)
    globalThis.dispatchEvent(new CustomEvent('ts-plate-change', { detail: { plate } }))
  }, [plate, glowColor])

  useEffect(() => {
    applyGlow(glow)
    localStorage.setItem(STORAGE_GLOW, glow)
    globalThis.dispatchEvent(new CustomEvent('ts-glow-change', { detail: { glow } }))
  }, [glow])

  useEffect(() => {
    applyGlowColor(glowColor, plate)
    localStorage.setItem(STORAGE_GLOW_COLOR, glowColor)
    globalThis.dispatchEvent(new CustomEvent('ts-glow-color-change', { detail: { glowColor } }))
  }, [glowColor, plate])

  useEffect(() => {
    const onThemeChange = event => {
      if (event.detail?.theme) setTheme(event.detail.theme)
    }
    const onPlateChange = event => {
      if (event.detail?.plate) setPlate(event.detail.plate)
    }
    const onGlowChange = event => {
      if (event.detail?.glow) setGlow(event.detail.glow)
    }
    const onGlowColorChange = event => {
      if (event.detail?.glowColor) setGlowColor(event.detail.glowColor)
    }
    globalThis.addEventListener('ts-theme-change', onThemeChange)
    globalThis.addEventListener('ts-plate-change', onPlateChange)
    globalThis.addEventListener('ts-glow-change', onGlowChange)
    globalThis.addEventListener('ts-glow-color-change', onGlowColorChange)
    return () => {
      globalThis.removeEventListener('ts-theme-change', onThemeChange)
      globalThis.removeEventListener('ts-plate-change', onPlateChange)
      globalThis.removeEventListener('ts-glow-change', onGlowChange)
      globalThis.removeEventListener('ts-glow-color-change', onGlowColorChange)
    }
  }, [])

  const isDark = theme === 'dark'
  const shellClass = floating
    ? 'fixed bottom-5 left-5 z-[80] flex items-end gap-2'
    : 'relative inline-flex items-center gap-2'
  const toggleClass = floating
    ? 'inline-flex h-12 items-center gap-2 rounded-lg bg-slate-950 px-4 text-sm font-bold text-white shadow-xl transition hover:-translate-y-0.5 hover:bg-slate-800'
    : 'inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white/90 px-3 py-2 text-xs font-bold text-slate-600 shadow-sm transition hover:-translate-y-0.5 hover:bg-white'
  const paletteClass = floating
    ? 'inline-flex h-12 items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 text-sm font-bold text-slate-700 shadow-xl transition hover:-translate-y-0.5 hover:bg-slate-50'
    : 'inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white/90 px-3 py-2 text-xs font-bold text-slate-600 shadow-sm transition hover:-translate-y-0.5 hover:bg-white'
  const glowClass = floating
    ? 'inline-flex h-12 items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 text-sm font-bold text-slate-700 shadow-xl transition hover:-translate-y-0.5 hover:bg-slate-50'
    : 'inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white/90 px-3 py-2 text-xs font-bold text-slate-600 shadow-sm transition hover:-translate-y-0.5 hover:bg-white'

  return (
    <div className={shellClass}>
      <button
        type="button"
        onClick={() => setTheme(isDark ? 'light' : 'dark')}
        className={toggleClass}
        aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
        title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      >
        {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        <span>{isDark ? 'Light Mode' : 'Dark Mode'}</span>
      </button>

      <button
        type="button"
        onClick={() => setOpen(value => !value)}
        className={paletteClass}
        aria-label="Choose background plate"
        title="Choose background plate"
      >
        <Palette className="h-4 w-4" />
        <span>{floating ? 'Themes' : `${selectedPlate.number}. ${selectedPlate.name}`}</span>
      </button>

      <button
        type="button"
        onClick={() => setOpen(value => !value)}
        className={glowClass}
        aria-label="Choose margin glow"
        title="Choose margin glow"
      >
        <Sparkles className="h-4 w-4" />
        <span>Glow: {selectedGlow.name}</span>
      </button>

      {open && (
        <div
          className={clsx(
            'absolute z-[90] w-[min(390px,calc(100vw-2rem))] rounded-lg border border-slate-200 bg-white/95 p-3 text-slate-700 shadow-2xl backdrop-blur-xl',
            floating ? 'bottom-14 left-0' : 'right-0 top-12'
          )}
        >
          <div className="mb-2 flex items-center justify-between gap-3">
            <p className="text-xs font-black uppercase tracking-wide text-slate-500">Background Plates</p>
            <span className="text-xs font-bold text-slate-600">{selectedPlate.number}/{PLATES.length}</span>
          </div>
          <div className="grid max-h-64 grid-cols-3 gap-2 overflow-y-auto pr-1">
            {PLATES.map(item => (
              <button
                key={item.id}
                type="button"
                onClick={() => setPlate(item.id)}
                className={clsx(
                  'group relative min-h-20 rounded-lg border p-2 text-left shadow-sm transition hover:-translate-y-0.5',
                  item.id === plate ? 'border-cyan-500 ring-2 ring-cyan-200' : 'border-slate-200 hover:border-cyan-200'
                )}
                style={{ background: `linear-gradient(145deg, ${item.start}, ${item.mid} 52%, ${item.end})` }}
                title={`${item.number}. ${item.name}`}
              >
                <span className="block text-[11px] font-black text-slate-700">{item.number}</span>
                <span className="mt-1 block text-xs font-bold leading-tight text-slate-700">{item.name}</span>
                {item.id === plate && (
                  <span className="absolute right-2 top-2 rounded-full bg-blue-600 p-1 text-white">
                    <Check className="h-3 w-3" />
                  </span>
                )}
              </button>
            ))}
          </div>

          <div className="mt-4 border-t border-slate-200 pt-3">
            <div className="mb-2 flex items-center justify-between gap-3">
              <p className="text-xs font-black uppercase tracking-wide text-slate-500">Margin Glow</p>
              <span className="text-xs font-bold text-blue-700">{selectedGlow.name}</span>
            </div>
            <div className="grid grid-cols-4 gap-2">
              {GLOWS.map(item => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setGlow(item.id)}
                  className={clsx(
                    'relative min-h-14 rounded-lg border bg-[#edf5ff] px-2 py-2 text-left text-xs font-bold text-slate-700 transition hover:-translate-y-0.5',
                    item.id === glow ? 'border-cyan-500 ring-2 ring-cyan-200' : 'border-slate-200 hover:border-cyan-200'
                  )}
                  style={{
                    boxShadow: item.id === 'none'
                      ? 'none'
                      : `0 ${item.cardY} ${item.cardBlur} rgba(${selectedGlowColor.color || selectedPlate.accent},${item.cardAlpha}), 0 0 ${item.cardSpread} rgba(${selectedGlowColor.color2 || selectedPlate.accent2},${item.cardSoftAlpha})`,
                  }}
                  title={`${item.number}. ${item.name}`}
                >
                  <span className="block text-[11px] text-slate-500">{item.number}</span>
                  <span className="block">{item.name}</span>
                  {item.id === glow && (
                    <span className="absolute right-1.5 top-1.5 rounded-full bg-blue-600 p-0.5 text-white">
                      <Check className="h-2.5 w-2.5" />
                    </span>
                  )}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-4 border-t border-slate-200 pt-3">
            <div className="mb-2 flex items-center justify-between gap-3">
              <p className="text-xs font-black uppercase tracking-wide text-slate-500">Glow Color</p>
              <span className="text-xs font-bold text-blue-700">{selectedGlowColor.name}</span>
            </div>
            <div className="grid grid-cols-4 gap-2">
              {GLOW_COLORS.map(item => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setGlowColor(item.id)}
                  className={clsx(
                    'relative min-h-12 rounded-lg border px-2 py-2 text-left text-xs font-bold text-slate-700 transition hover:-translate-y-0.5',
                    item.id === glowColor ? 'border-cyan-500 ring-2 ring-cyan-200' : 'border-slate-200 hover:border-cyan-200'
                  )}
                  style={{
                    background: `linear-gradient(145deg, rgba(${item.color || selectedPlate.accent},0.22), rgba(${item.color2 || selectedPlate.accent2},0.16))`,
                    boxShadow: `0 10px 24px rgba(${item.color || selectedPlate.accent},0.16), 0 0 22px rgba(${item.color2 || selectedPlate.accent2},0.10)`,
                  }}
                  title={`${item.number}. ${item.name}`}
                >
                  <span className="block">{item.name}</span>
                  {item.id === glowColor && (
                    <span className="absolute right-1.5 top-1.5 rounded-full bg-blue-600 p-0.5 text-white">
                      <Check className="h-2.5 w-2.5" />
                    </span>
                  )}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const EMPTY_DATE_VALUES = new Set([
  '',
  '-',
  '--',
  'na',
  'n/a',
  'none',
  'null',
  'undefined',
  'tbd',
  'to be confirmed',
  'not mentioned',
])

const MONTHS = {
  jan: 0,
  january: 0,
  feb: 1,
  february: 1,
  mar: 2,
  march: 2,
  apr: 3,
  april: 3,
  may: 4,
  jun: 5,
  june: 5,
  jul: 6,
  july: 6,
  aug: 7,
  august: 7,
  sep: 8,
  sept: 8,
  september: 8,
  oct: 9,
  october: 9,
  nov: 10,
  november: 10,
  dec: 11,
  december: 11,
}

function cleanDateValue(value) {
  const text = String(value ?? '').trim()
  if (!text || EMPTY_DATE_VALUES.has(text.toLowerCase())) return ''
  return text
}

function makeDate(year, monthIndex, day) {
  const date = new Date(Number(year), Number(monthIndex), Number(day))
  if (
    date.getFullYear() !== Number(year) ||
    date.getMonth() !== Number(monthIndex) ||
    date.getDate() !== Number(day)
  ) {
    return null
  }
  return date
}

function parseYear(value) {
  const year = Number(value)
  if (!Number.isFinite(year)) return null
  return year < 100 ? 2000 + year : year
}

function parseRequirementDate(value) {
  const text = cleanDateValue(value)
  if (!text) return null

  const iso = /\b(\d{4})-(\d{2})-(\d{2})\b/.exec(text)
  if (iso) return makeDate(iso[1], Number(iso[2]) - 1, iso[3])

  const numericDayFirst = /\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b/.exec(text)
  if (numericDayFirst) {
    const year = parseYear(numericDayFirst[3])
    if (year) return makeDate(year, Number(numericDayFirst[2]) - 1, numericDayFirst[1])
  }

  const dayMonth = /\b(\d{1,2})\s*([A-Za-z]{3,9})\.? ,?\s*(\d{2,4})?\b/.exec(text)
  if (dayMonth) {
    const month = MONTHS[dayMonth[2].toLowerCase()]
    const year = parseYear(dayMonth[3] || new Date().getFullYear())
    if (month !== undefined && year) return makeDate(year, month, dayMonth[1])
  }

  const monthDay = /\b([A-Za-z]{3,9})\.?\s*(\d{1,2}),?\s*(\d{2,4})?\b/.exec(text)
  if (monthDay) {
    const month = MONTHS[monthDay[1].toLowerCase()]
    const year = parseYear(monthDay[3] || new Date().getFullYear())
    if (month !== undefined && year) return makeDate(year, month, monthDay[2])
  }

  return null
}

function daysInclusive(start, end) {
  if (!start || !end) return null
  const ms = end.getTime() - start.getTime()
  return Math.round(ms / 86400000) + 1
}

function swappedIndianDateFromIso(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(cleanDateValue(value))
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  if (day < 1 || day > 12) return null
  return makeDate(year, day - 1, month)
}

function maybeCorrectSwappedRange(req, start, end) {
  const expectedDays = Number(req?.duration_days || 0)
  if (!start || !end || !Number.isFinite(expectedDays) || expectedDays <= 0) return null

  const originalDays = daysInclusive(start, end)
  if (!originalDays || originalDays <= expectedDays + 7) return null

  const swappedStart = swappedIndianDateFromIso(req?.timeline_start)
  const swappedEnd = swappedIndianDateFromIso(req?.timeline_end)
  if (!swappedStart || !swappedEnd || swappedEnd < swappedStart) return null

  const swappedDays = daysInclusive(swappedStart, swappedEnd)
  if (Math.abs(swappedDays - expectedDays) <= 1) {
    return { start: swappedStart, end: swappedEnd }
  }

  return null
}

function formatDate(date, includeYear = true) {
  return date.toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    ...(includeYear ? { year: 'numeric' } : {}),
  })
}

function formatDateRange(start, end) {
  if (start && end) {
    if (start.getTime() === end.getTime()) return formatDate(start)
    const sameYear = start.getFullYear() === end.getFullYear()
    return `${formatDate(start, !sameYear)}-${formatDate(end)}`
  }
  if (start) return formatDate(start)
  if (end) return formatDate(end)
  return 'TBD'
}

export function formatRequirementSchedule(req) {
  const startText = cleanDateValue(req?.timeline_start)
  const endText = cleanDateValue(req?.timeline_end)
  const start = parseRequirementDate(startText)
  const end = parseRequirementDate(endText)

  const correctedRange = maybeCorrectSwappedRange(req, start, end)
  if (correctedRange) return formatDateRange(correctedRange.start, correctedRange.end)
  if (startText || endText) return formatDateRange(start, end) || cleanDateValue(`${startText} ${endText}`) || 'TBD'

  const trainingDates = cleanDateValue(req?.training_dates || req?.preferred_dates)
  if (!trainingDates) return 'TBD'

  const rangeParts = trainingDates.split(/\s+(?:to|until|through|till)\s+/i)
  if (rangeParts.length >= 2) {
    const rangeStart = parseRequirementDate(rangeParts[0])
    const rangeEnd = parseRequirementDate(rangeParts[1])
    if (rangeStart || rangeEnd) return formatDateRange(rangeStart, rangeEnd)
  }

  const parsedTrainingDate = parseRequirementDate(trainingDates)
  return parsedTrainingDate ? formatDate(parsedTrainingDate) : trainingDates
}

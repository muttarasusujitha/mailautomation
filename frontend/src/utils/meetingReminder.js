const REMINDER_WINDOW_MS = 5 * 60 * 1000

export function reminderKey(item = {}, time = 0) {
  return `${item.email_id || ''}:${item.calendar_event_id || item.schedule_id || ''}:${time}`
}

export function isMeetingReminderDue(_item = {}, time = 0) {
  if (!time) return false
  const diff = time - Date.now()
  return diff > 0 && diff <= REMINDER_WINDOW_MS
}

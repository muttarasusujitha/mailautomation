// Start the host warning early enough to open the meeting and check readiness.
export const MEETING_ALARM_LEAD_MS = 10 * 60 * 1000
export const MEETING_ALARM_FOLLOW_UP_MS = 10 * 60 * 1000

export function reminderKey(item = {}, time = 0) {
  return `${item.email_id || ''}:${item.calendar_event_id || item.schedule_id || ''}:${time}`
}

export function isMeetingReminderDue(_item = {}, time = 0) {
  if (!time) return false
  const diff = time - Date.now()
  return diff > 0 && diff <= MEETING_ALARM_LEAD_MS
}

export function isMeetingFollowUpAlarmDue(_item = {}, time = 0) {
  if (!time) return false
  const elapsed = Date.now() - time
  // A short grace window handles a backgrounded browser tab without producing
  // an alert long after a completed meeting.
  return elapsed >= MEETING_ALARM_FOLLOW_UP_MS && elapsed <= MEETING_ALARM_FOLLOW_UP_MS + (2 * 60 * 1000)
}

// Shared wording for both shortlist screens. Only confirmed facts enter messages.
import { linkedinProfileUrl } from './trainerIdentity.js'
const text = value => value == null ? '' : String(value).trim()
const known = value => !!text(value) && !/^(to be confirmed|tbc|tbd|unknown|n\/a)(\b|$)/i.test(text(value))
const number = value => Number.isFinite(Number(value)) && Number(value) > 0 ? Number(value) : 0
const domain = req => req.technology_needed || req.domain || 'Training'
const greeting = trainer => `Dear ${trainer.name || trainer.trainer_name || 'Trainer'},`
const signature = 'Regards,\nClahan Technologies'
const compose = (trainer, subject, sections) => ({ subject, body: [greeting(trainer), ...sections.filter(Boolean), signature].join('\n\n') })
const rows = entries => entries.filter(([, value]) => text(value)).map(([label, value]) => `- ${label}: ${value}`).join('\n')
export function proposal(req = {}) {
  const page = req.pipeline_target || req.pipeline_page
  if (page === 'shortlist' || page === 'shortlist1') return page === 'shortlist'
  return /proposal/i.test(req.batch_flow || req.batch_type || req.requirement_type || '')
}
export function trainingDays(req = {}) {
  return number(req.duration_days || req.commercial_working_days)
    || number(text(req.duration_text || req.duration).match(/\b(\d+(?:\.\d+)?)\s*(?:(?:training|working|business)\s+)?days?\b/i)?.[1])
}
export function trainerOffer(req = {}, trainer = {}) {
  const days = trainingDays(req)
  let amount = 0
  let total = false
  if (proposal(req)) {
    const tier = trainer.clahan_skill_tier || req.clahan_skill_tier || 'standard'
    amount = number(trainer.clahan_offer_per_day || req.clahan_offer_per_day) || ({ standard: 14000, advanced: 15000, specialist: 16000 }[tier] || 0)
    if (amount < 14000 || amount > 16000) return ''
    if (days >= 5) { amount *= days; total = true }
  } else {
    const budget = number(req.budget_total)
    const daily = number(req.client_budget_per_day || req.budget_per_day)
    if (budget) { amount = budget * .7; total = true }
    else if (daily) {
      total = !!days && (days >= 5 || daily < 10000)
      amount = daily * .7 * (total ? days : 1)
    }
  }
  return amount ? `INR ${Math.round(amount).toLocaleString('en-IN')} ${total ? 'total engagement' : 'per training day'}, inclusive of applicable TDS` : ''
}
function missingProfile(trainer) {
  const items = []
  if (![trainer.resume, trainer.resume_text, trainer.resume_url, trainer.cv_url, trainer.upload_id].some(Boolean)) items.push('Updated trainer profile/CV')
  if (![trainer.linkedin, trainer.linkedin_url, trainer.linkedin_profile].some(value => linkedinProfileUrl(value))) items.push('LinkedIn profile')
  if (!(trainer.experience_years || trainer.experience || trainer.summary)) items.push('Relevant implementation and training experience')
  return items
}
export function mail1Template(trainer, req, hasDetails, details = {}, isReminder = false, reminderNum = 0) {
  const course = details.domain || domain(req)
  const isProposal = proposal(req)
  const dates = req.training_dates || req.preferred_dates || [req.timeline_start, req.timeline_end].filter(Boolean).join(' to ')
  const requested = hasDetails ? [] : missingProfile(trainer)
  const offer = trainerOffer(req, trainer)
  return compose(trainer, `${isReminder ? `[Reminder ${reminderNum}] ` : ''}${isProposal ? 'Proposed' : 'Confirmed'} Training Requirement - ${course}`, [
    isReminder ? 'Following up on our earlier training enquiry.' : `We are contacting you about ${isProposal ? 'a proposed corporate training engagement' : 'a confirmed client training requirement'}.`,
    'Training scope:\n' + rows([
      ['Technology', course], ['Audience', req.audience_level || req.participant_level],
      ['Participants', req.participant_count || req.participants],
      ['Training dates', dates || 'To be confirmed'],
      ['Duration', req.duration_text || req.duration || (trainingDays(req) ? `${trainingDays(req)} training days` : 'To be confirmed')],
      ['Training time', req.training_time || req.timing || req.session_timing],
      ['Mode', req.mode || 'To be confirmed'], ['Location', req.preferred_location || req.location || 'To be confirmed'],
      ['Experience required', req.experience_required || (req.min_experience_years ? `${req.min_experience_years}+ years` : '')],
    ]),
    offer ? `Offered trainer commercial:\n${offer}\nPlease confirm whether this offer works for you.` : 'Clahan will confirm the engagement amount once the commercial inputs are available.',
    `Please confirm your interest, delivery feasibility, and ${known(dates) ? 'availability for the stated training dates' : 'tentative availability; calendar dates remain to be confirmed'}.`,
    requested.length ? 'Please share the following outstanding details:\n' + requested.map(item => `- ${item}`).join('\n') : '',
    'Please share three convenient interview/discussion slots, each with a date, start time, and time zone. These are discussion options, not confirmed training dates.',
    'Format only; replace these placeholders with your actual availability:\n- [Your available date 1], [time], [time zone]\n- [Your available date 2], [time], [time zone]\n- [Your available date 3], [time], [time zone]',
    'Please identify any scope changes or lab prerequisites needed for delivery. Clahan will coordinate the ToC and any requested lab estimate for review.',
  ])
}
export function mail2FollowupTemplate(trainer, req, missingItems = null) {
  const items = (Array.isArray(missingItems) ? missingItems : missingProfile(trainer))
    .filter(item => !/\b(toc|agenda|commercials?|lab cost|lab support)\b/i.test(item))
  return compose(trainer, `Re: Training Requirement - ${domain(req)} | Outstanding Details`, [
    'Thank you for your response.',
    items.length ? 'Please share only these outstanding details:\n' + items.map(item => `- ${item}`).join('\n') : 'Please confirm your current availability so we can coordinate the next discussion.',
    'You do not need to resend information already shared.',
  ])
}
export function mail3Template(trainer, req, trainerDates) {
  return compose(trainer, `Discussion Availability - ${domain(req)}`, [
    'Please share your three preferred discussion slots, including the date, start time, and time zone for each.',
    trainerDates ? `Availability already shared:\n${trainerDates}` : 'Use one line per option: date, start time (AM/PM), time zone.',
    'We will send a meeting invitation once a slot is agreed.',
  ])
}
export const mail3SlotClarificationTemplate = trainer => mail3Template(trainer, {technology_needed: 'Slot clarification'}, '')
export const mail3TooManySlotsTemplate = trainer => mail3Template(trainer, {technology_needed: 'Select your preferred three slots'}, '')
export function mail4Template(trainer, req, interviewLink, platform, dateTime) {
  return compose(trainer, `Interview Schedule - ${domain(req)}`, [
    dateTime && interviewLink ? 'Your interview/discussion is scheduled as follows:' : 'The interview arrangements are awaiting confirmation.',
    rows([['Date and time', dateTime || 'To be confirmed'], ['Platform', platform || 'To be confirmed'], ['Meeting link', interviewLink || 'To be confirmed']]),
    'Please acknowledge the invitation or let us know if you need a change.',
  ])
}
export function mail5SelectedTemplate(trainer, req) {
  return compose(trainer, `Client Decision - ${domain(req)}`, [
    trainer.selected || trainer.selection_status === 'selected' ? 'The client has selected you for this training engagement.' : 'The client decision is awaiting confirmation.',
    'Clahan will coordinate the approved scope, schedule, and commercial documentation before final training confirmation.',
  ])
}
export function mail5RejectedTemplate(trainer, req) {
  return compose(trainer, `Update on Training Requirement - ${domain(req)}`, [
    `Thank you for your time and interest in the ${domain(req)} engagement.`,
    'We will not be proceeding with your profile for this engagement. We appreciate your participation and will consider your profile for relevant future requirements.',
  ])
}
export function mailTocAutoTemplate(trainer, req) {
  return compose(trainer, `Scope and Lab Review - ${domain(req)}`, [
    'Please confirm the proposed course coverage and identify any changes needed for the audience and available training hours.',
    'Please identify the tools, software, access requirements, and participant prerequisites needed for the labs. Clahan will coordinate the agenda and requested lab estimate for review.',
    'Final delivery scope and schedule will be confirmed separately.',
  ])
}
export function mailTrainingConfirmedTemplate(trainer, req, contactName, contactPhone, contactEmail, trainingDate, venue) {
  return compose(trainer, `Training Coordination - ${domain(req)}`, [
    'Please review the training arrangements below.',
    rows([['Technology', domain(req)], ['Training dates', trainingDate || req.training_dates || 'To be confirmed'],
      ['Training time', req.training_time || req.timing || req.session_timing || 'To be confirmed'],
      ['Mode', req.mode || 'To be confirmed'], ['Venue / joining details', venue || 'To be confirmed'],
      ['Coordinator', contactName], ['Phone', contactPhone], ['Email', contactEmail]]),
    'Please acknowledge the arrangements and report any outstanding prerequisites before delivery.',
  ])
}
export function trainerCommercialNegotiationTemplate(trainer, req, quote, target) {
  return compose(trainer, `Commercial Discussion - ${domain(req)}`, [
    'Thank you for your response. Clahan would like to offer the following engagement amount:',
    trainerOffer(req, trainer) || 'Commercial amount awaiting confirmation.',
    'Please confirm whether the offer works for you, or let us know for review.',
  ])
}

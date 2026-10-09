import assert from 'node:assert/strict'
import test from 'node:test'
import { mail1Template } from './workflowTemplates.js'

const trainer = { name: 'Suresh Reddy', resume_text: 'Stored corporate DevOps CV' }
const confirmed = {
  batch_flow: 'confirmed',
  technology_needed: 'DevOps',
  training_dates: '10 September 2026 to 7 October 2026',
  duration_days: 20,
  mode: 'Online',
  participant_count: 20,
  budget_total: 130000,
}

test('confirmed Mail 1 shows the client commercial without a trainer offer', () => {
  const mail = mail1Template(trainer, confirmed, false, {})
  assert.match(mail.body, /Client commercial:/)
  assert.match(mail.body, /130,?000|1,30,000/)
  assert.doesNotMatch(mail.body, /Offered trainer commercial/i)
  assert.doesNotMatch(mail.body, /confirm whether this offer/i)
  assert.doesNotMatch(mail.body, /91,?000/)
  assert.match(mail.body, /three convenient interview\/discussion slots/)
  assert.doesNotMatch(mail.body, /Updated trainer profile\/CV/)
})

test('confirmed Mail 1 asks for a CV only when none is stored', () => {
  const mail = mail1Template({ name: 'Suresh Reddy' }, confirmed, false, {})
  assert.match(mail.body, /Updated trainer profile\/CV/)
})

test('proposal Mail 1 still uses the trainer offer', () => {
  const mail = mail1Template(
    { name: 'Asha' },
    { batch_flow: 'proposal', pipeline_target: 'shortlist', technology_needed: 'Java', duration_days: 10 },
    false,
    {},
  )
  assert.match(mail.body, /Offered trainer commercial/)
  assert.match(mail.body, /Please confirm whether this offer works for you/)
})

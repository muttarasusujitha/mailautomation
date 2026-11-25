import test from 'node:test'
import assert from 'node:assert/strict'
import { firstContactMail, trainerName } from './trainerOutreachMail.js'

test('the first-contact mail uses the page mail fields', () => {
  const mail = firstContactMail({
    lead: { trainer_name: 'Ravi Kumar', domain: 'Python' },
    mailContext: { domain: 'Python for data teams', duration: '5 days', mode: 'Online', participants: '20', requirement_note: 'Weekend batch' },
  })
  assert.equal(mail.subject, 'Training Opportunity - Python for data teams')
  assert.equal(mail.body, 'Dear Ravi Kumar,\n\n' +
    'We found your LinkedIn trainer profile while searching for Python for data teams expertise.\n\n' +
    'We have a training requirement that may match your profile:\n' +
    'Domain: Python for data teams\nDuration: 5 days\nMode: Online\nParticipants: 20\n\nRequirement note:\nWeekend batch\n\n' +
    'Please confirm your interest, availability, commercials, and a brief trainer profile/TOC if relevant.' +
    '\n\nRegards,\nRecruitment Team\nClahan Technologies')
})

test('empty mail fields fall back to the lead and leave out empty lines', () => {
  const mail = firstContactMail({ lead: { name: '', headline: 'Java mentor', domain: 'Java' }, foundOn: 'Naukri profile' })
  assert.equal(mail.subject, 'Training Opportunity - Java')
  assert.match(mail.body, /^Dear Java mentor,\n\nWe found your Naukri profile while searching for Java expertise\./)
  assert.match(mail.body, /profile:\nDomain: Java\n\nPlease confirm/)
  assert.equal(trainerName({}), 'Trainer')
})

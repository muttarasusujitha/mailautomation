import test from 'node:test'
import assert from 'node:assert/strict'
import { linkedInSearchPayload, mergeSearchLeads, visibleSearchLeads } from './leadSearchFeedback.js'

test('client and trainer searches both post into LinkedIn search with the same domains', () => {
  const client = linkedInSearchPayload('client', '')
  const trainer = linkedInSearchPayload('trainer', '')
  assert.equal(client.mode, 'client')
  assert.equal(trainer.mode, 'trainer')
  assert.deepEqual(client.domains, ['Python', 'AWS'])
  assert.deepEqual(trainer.domains, ['Python', 'AWS'])
  assert.equal(client.save, true)
  assert.equal(trainer.save, true)
  assert.equal(client.search_provider, 'auto')
  assert.equal(trainer.search_provider, 'auto')
  assert.equal(trainer.max_results, 60)
  assert.equal(client.max_results, 50)
})

test('an entered domain list is shared by both LinkedIn search modes', () => {
  assert.deepEqual(linkedInSearchPayload('client', 'SAP, Python').domains, ['SAP', 'Python'])
  assert.deepEqual(linkedInSearchPayload('trainer', 'SAP, Python').domains, ['SAP', 'Python'])
})

test('fresh search matches stay in the LinkedIn search list with saved leads', () => {
  const saved = [{ lead_id: 'CL-1', source_url: 'https://www.linkedin.com/posts/old' }]
  const results = [{ lead_id: 'CL-2', source_url: 'https://www.linkedin.com/posts/new', domain: 'Python' }]
  const merged = mergeSearchLeads(saved, results)
  assert.deepEqual(merged.map(lead => lead.lead_id), ['CL-2', 'CL-1'])
  assert.equal(mergeSearchLeads(saved, [{ lead_id: 'CL-1', source_url: 'https://www.linkedin.com/posts/old' }]).length, 1)
})

test('a finished search displays the fetched profiles even when they were already saved', () => {
  const saved = []
  const results = [
    { lead_id: 'TPL-1', trainer_name: 'Asha Rao', source_url: 'https://www.linkedin.com/in/asha' },
    { name: 'Ravi Kumar', linkedin_url: 'https://www.linkedin.com/in/ravi' },
  ]
  const shown = visibleSearchLeads(saved, results, true)
  assert.deepEqual(shown.map(lead => lead.lead_id || lead.linkedin_url), ['TPL-1', 'https://www.linkedin.com/in/ravi'])
  assert.deepEqual(visibleSearchLeads([{ lead_id: 'saved' }], results, false).map(lead => lead.lead_id), ['saved'])
})

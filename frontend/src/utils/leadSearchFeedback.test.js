import test from 'node:test'
import assert from 'node:assert/strict'
import { linkedInSearchPayload, mergeSearchLeads, searchResultLeads } from './leadSearchFeedback.js'

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

test('saved trainer profiles stay visible when the latest search matches nothing', () => {
  const leads = [
    { lead_id: 'TPL-1', domain: 'AWS', source_url: 'https://www.linkedin.com/in/a' },
    { lead_id: 'TPL-2', domain: 'Python', source_url: 'https://www.linkedin.com/in/b' },
  ]
  const visible = searchResultLeads(leads, {
    selectedDomain: 'soft skills',
    showSearchMatches: true,
    results: [{ source_url: 'https://www.linkedin.com/in/missing' }],
  })
  assert.deepEqual(visible.map(lead => lead.lead_id), ['TPL-1', 'TPL-2'])
  assert.deepEqual(
    searchResultLeads(leads, { selectedDomain: 'AWS' }).map(lead => lead.lead_id),
    ['TPL-1'],
  )
})

test('fresh search matches stay in the LinkedIn search list with saved leads', () => {
  const saved = [{ lead_id: 'CL-1', source_url: 'https://www.linkedin.com/posts/old' }]
  const results = [{ lead_id: 'CL-2', source_url: 'https://www.linkedin.com/posts/new', domain: 'Python' }]
  const merged = mergeSearchLeads(saved, results)
  assert.deepEqual(merged.map(lead => lead.lead_id), ['CL-2', 'CL-1'])
  assert.equal(mergeSearchLeads(saved, [{ lead_id: 'CL-1', source_url: 'https://www.linkedin.com/posts/old' }]).length, 1)
})

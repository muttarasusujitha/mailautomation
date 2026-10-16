import test from 'node:test'
import assert from 'node:assert/strict'
import { collectionOutcomeLines, linkedInSearchPayload, mergeSearchLeads, outcomeLine } from './leadSearchFeedback.js'

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

test('a catalog scan without a per-domain target does not say the target was zero', () => {
  const domains = ['DevOps', 'Python', 'Java', 'Cloud', 'SAP', 'React', 'AWS']
  const lines = collectionOutcomeLines(domains.map(domain => ({ domain, matched: 0, status: 'no_match' })))
  assert.deepEqual(lines, ['7 domains had no matching posts.'])
  assert.equal(outcomeLine({ domain: 'Python', matched: 3, target: 20, target_met: false }), 'Python: 3 found (target: 20). Partial results; the target is not guaranteed.')
})

test('fresh search matches stay in the LinkedIn search list with saved leads', () => {
  const saved = [{ lead_id: 'CL-1', source_url: 'https://www.linkedin.com/posts/old' }]
  const results = [{ lead_id: 'CL-2', source_url: 'https://www.linkedin.com/posts/new', domain: 'Python' }]
  const merged = mergeSearchLeads(saved, results)
  assert.deepEqual(merged.map(lead => lead.lead_id), ['CL-2', 'CL-1'])
  assert.equal(mergeSearchLeads(saved, [{ lead_id: 'CL-1', source_url: 'https://www.linkedin.com/posts/old' }]).length, 1)
})

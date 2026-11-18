import test from 'node:test'
import assert from 'node:assert/strict'
import { collectionOutcomeLines, leadSourceLabel, linkedInSearchPayload, mergeSearchLeads, outcomeLine, runStartedAfter, searchReportGroups, sourceReportLines, visibleSearchLeads } from './leadSearchFeedback.js'

test('client and trainer searches both post into LinkedIn search with the same domains', () => {
  const client = linkedInSearchPayload('client', '')
  const trainer = linkedInSearchPayload('trainer', '')
  assert.equal(client.mode, 'client')
  assert.equal(trainer.mode, 'trainer')
  assert.deepEqual(client.domains, ['Python'])
  assert.deepEqual(trainer.domains, ['Python'])
  assert.equal(client.save, true)
  assert.equal(trainer.save, true)
  assert.equal(client.search_provider, 'auto')
  assert.equal(trainer.search_provider, 'auto')
  assert.equal(trainer.max_results, 100)
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

test('an empty search keeps saved profiles on screen', () => {
  const saved = [{ lead_id: 'TPL-1', source_url: 'https://www.linkedin.com/in/ada' }]
  assert.deepEqual(visibleSearchLeads(saved, [], true).map(lead => lead.lead_id), ['TPL-1'])
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

test('source report lines say which sources worked and why others did not', () => {
  const lines = sourceReportLines({ sources: [
    { source: 'linkedin_account', label: 'LinkedIn account', status: 'paused', qualified: 0, reason: 'Paused until 10:00 UTC.' },
    { source: 'bing', label: 'Bing', status: 'ok', qualified: 18, reason: '' },
    { source: 'brave', label: 'Brave Search', status: 'blocked', qualified: 0, reason: 'Captcha page.' },
  ] })
  assert.deepEqual(lines.map(line => line.text), [
    'LinkedIn account: paused (Paused until 10:00 UTC.)',
    'Bing: worked, 18 matching profiles',
    'Brave Search: blocked (Captcha page.)',
  ])
  assert.deepEqual(lines.map(line => line.ok), [false, true, false])
  assert.deepEqual(sourceReportLines({}), [])
})

test('lead source label names the web engines that found a profile', () => {
  assert.equal(leadSourceLabel({ discovery_provider: 'trainer_finder', found_by: ['bing', 'mojeek'] }), 'Web search (bing, mojeek)')
  assert.equal(leadSourceLabel({ discovery_provider: 'public_fallback' }), 'Public indexed search fallback')
  assert.equal(leadSourceLabel({ discovery_provider: 'linkedin_account', source: 'linkedin' }), 'LinkedIn account')
  assert.equal(leadSourceLabel({ source: 'naukri' }), 'naukri')
})

test('a search-public report lists each domain and each source, including skipped domains', () => {
  const report = {
    sources: [{ source: 'duckduckgo', label: 'DuckDuckGo', status: 'ok', qualified: 2, note: 'Failed on 1 of 2 searches: refused' }],
    domain_outcomes: [
      { domain: 'Python', target: 10, matched: 2, target_met: false, status: 'partial',
        sources: [{ source: 'duckduckgo', label: 'DuckDuckGo', status: 'ok', qualified: 2 }] },
      { domain: 'AWS', target: 0, matched: 0, status: 'not_run', limit_reason: 'Not searched: the search service stopped answering.', sources: [] },
    ],
  }
  assert.deepEqual(searchReportGroups(report), [
    { key: '0-Python', heading: 'Python: 2 found (target: 10). Partial results; the target is not guaranteed.',
      lines: [{ key: 'duckduckgo', ok: true, text: 'DuckDuckGo: worked, 2 matching profiles' }] },
    { key: '1-AWS', heading: 'AWS: Not searched: the search service stopped answering.', lines: [] },
  ])
  assert.deepEqual(searchReportGroups({ sources: report.sources }), [{
    key: 'sources', heading: '',
    lines: [{ key: 'duckduckgo', ok: true, text: 'DuckDuckGo: worked, 2 matching profiles Failed on 1 of 2 searches: refused' }],
  }])
  assert.deepEqual(searchReportGroups({}), [])
})

test('a saved run belongs to a search only when it started after that search', () => {
  const startedAt = Date.parse('2026-11-16T09:00:00Z')
  assert.equal(runStartedAfter({ started_at: '2026-11-16T09:00:30' }, startedAt), true)
  assert.equal(runStartedAfter({ started_at: '2026-11-16T08:59:30.123456' }, startedAt), true)
  assert.equal(runStartedAfter({ started_at: '2026-11-16T08:50:00Z' }, startedAt), false)
  assert.equal(runStartedAfter({ started_at: '2026-11-16T14:40:00+05:30' }, startedAt), true)
  assert.equal(runStartedAfter({}, startedAt), false)
})

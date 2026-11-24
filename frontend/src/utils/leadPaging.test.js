import test from 'node:test'
import assert from 'node:assert/strict'
import {
  LEAD_PAGE_SIZE, chunk, domainChips, leadListParams, leadsWithoutEmail, listPage, outreachReadyLeads,
  pageSummary, pageToReload, statusCountInView, statusTotal, sumResults,
} from './leadPaging.js'

test('list parameters page through the server and leave out empty filters', () => {
  assert.deepEqual(leadListParams({ page: 3, status: 'all', q: '  ', topic: '', domainExact: 'all' }), {
    page: 3, page_size: LEAD_PAGE_SIZE, include_counts: true,
  })
  assert.deepEqual(leadListParams({
    page: 0, status: 'new', statuses: ['new', 'reviewed'], q: ' python ', kind: 'shortlist', topic: ' SAP ',
    domainExact: '__none__', requirementScope: ' REQ-1 ', hasContact: true, includeCounts: false,
  }), {
    page: 1, page_size: 50, status: 'new', statuses: 'new,reviewed', q: 'python', kind: 'shortlist', topic: 'SAP',
    domain_exact: '__none__', requirement_scope: 'REQ-1', has_contact: true,
  })
})

test('a list response gives safe page fields and a page to reload after deletes', () => {
  assert.deepEqual(listPage({}), { total: 0, page: 1, pages: 1, pageSize: 50, counts: null })
  assert.deepEqual(listPage({ total: 120, page: 2, page_size: 50, pages: 3, counts: { by_status: {} } }),
    { total: 120, page: 2, pages: 3, pageSize: 50, counts: { by_status: {} } })
  assert.equal(pageToReload({ total: 100, pages: 2, leads: [] }, 3), 2)
  assert.equal(pageToReload({ total: 0, pages: 1, leads: [] }, 3), 0)
  assert.equal(pageToReload({ total: 120, pages: 3, leads: [{}] }, 3), 0)
  assert.deepEqual(pageSummary({ page: 3, pageSize: 50, total: 120 }), { first: 101, last: 120 })
  assert.deepEqual(pageSummary({ total: 0 }), { first: 0, last: 0 })
})

test('cards count the open status tab from the server counts', () => {
  const counts = { by_status: { new: 4, contacted: 2, outreach_sent: 1 } }
  assert.equal(statusTotal(counts), 7)
  assert.equal(statusCountInView(counts, 'all', 'contacted', 'outreach_sent'), 3)
  assert.equal(statusCountInView(counts, 'contacted', 'contacted', 'outreach_sent'), 2)
  assert.equal(statusCountInView(counts, 'new', 'contacted'), 0)
  assert.equal(statusTotal(null), 0)
})

test('domain chips keep the value the server filters and deletes by', () => {
  const chips = domainChips({ by_domain: [
    { value: 'python', domain: 'Python', total: 3, by_status: { new: 3 } },
    { value: '__none__', domain: 'Other', total: 1 },
  ] })
  assert.deepEqual(chips, [
    { value: 'python', label: 'Python', count: 3, byStatus: { new: 3 } },
    { value: '__none__', label: 'Other', count: 1, byStatus: {} },
  ])
  assert.deepEqual(domainChips(null), [])
})

test('shortlist bulk actions pick the page leads they apply to, in chunks', () => {
  const leads = [
    { lead_id: 'A', email: 'a@x.co', status: 'new' },
    { lead_id: 'B', contact_email: 'b@x.co', status: 'Contacted' },
    { lead_id: 'C', status: 'reviewed', email: ' ' },
    { lead_id: 'D', contact_email: 'd@x.co', status: 'rejected' },
    { lead_id: 'E', contact_email: 'e@x.co', status: 'reviewed' },
    { lead_id: 'F', contact_email: 'f@x.co', status: 'converted' },
  ]
  assert.deepEqual(leadsWithoutEmail(leads), ['C'])
  assert.deepEqual(outreachReadyLeads(leads).map(lead => lead.lead_id), ['A', 'E'])
  assert.deepEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
  assert.deepEqual(chunk(null), [])
  assert.deepEqual(sumResults([{ sent: 2, failed: 1 }, { sent: 1, failed: 0, error: 'HTTP 404' }], ['sent', 'failed']),
    { sent: 3, failed: 1, error: 'HTTP 404' })
})

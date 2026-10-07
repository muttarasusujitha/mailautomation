import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizePipelineItem } from './pipelineRecords.js'

test('flat API requirement fields remain available to invoice and PO forms', () => {
  const record = normalizePipelineItem({ requirement_id: 'REQ-1', technology_needed: 'Python', duration_days: 5, budget_total: 45000, client_name: 'Example', client_email: 'client@example.com' })
  assert.equal(record.requirement.duration_days, 5)
  assert.equal(record.requirement.budget_total, 45000)
  assert.equal(record.domain, 'Python')
  assert.equal(record.client.email, 'client@example.com')
})

test('nested records and server-provided client/PO data are preserved', () => {
  const client = { company: 'Client Co', email: 'finance@example.com' }
  const po = { po_id: 'PO-1', gst_rate: 0 }
  const requirement = { duration_days: 3, technology_needed: 'AWS' }
  const record = normalizePipelineItem({ requirement, client, client_po: po })
  assert.equal(record.requirement, requirement)
  assert.equal(record.client, client)
  assert.equal(record.client_po.gst_rate, 0)
  assert.equal(record.domain, 'AWS')
})

import test from 'node:test'
import assert from 'node:assert/strict'
import { resolveNavigationRoute } from './navigation.js'

const groups = [{ items: [
  { to: '/client-mail-pipeline', keywords: ['client pipeline', 'client mails'] },
  { to: '/invoices', keywords: ['invoice', 'manual invoice', 'billing'] },
  { to: '/purchase-orders', keywords: ['po', 'purchase order', 'generate po'] },
  { to: '/finance-approvals', keywords: ['po pdf', 'finance approvals'] },
] }]

test('sidebar search routes invoice and PO terms to their dedicated pages', () => {
  assert.equal(resolveNavigationRoute('invoice', groups), '/invoices')
  assert.equal(resolveNavigationRoute('billing', groups), '/invoices')
  assert.equal(resolveNavigationRoute('PO', groups), '/purchase-orders')
  assert.equal(resolveNavigationRoute('purchase order', groups), '/purchase-orders')
  assert.equal(resolveNavigationRoute('finance approvals', groups), '/finance-approvals')
})

test('sidebar search keeps the client pipeline route and ignores empty queries', () => {
  assert.equal(resolveNavigationRoute('client pipeline', groups), '/client-mail-pipeline')
  assert.equal(resolveNavigationRoute('   ', groups), null)
})

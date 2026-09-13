import test from 'node:test'
import assert from 'node:assert/strict'
import { isClientHandoffDelivered, pipelineStepComplete } from './handoffStatus.js'

const delivered = { client_slots_sent: true, client_slots_email_id: 'EML-1', slot_status: 'sent_to_client' }

test('later stages and cached timestamps cannot complete the handoff', () => {
  for (const trainer of [undefined, {}, { pipeline_status: 'interview_scheduled' }, { clientSlotsSentAt: Date.now() }]) {
    assert.equal(isClientHandoffDelivered(trainer), false)
    assert.equal(pipelineStepComplete(3, 8, trainer), false)
  }
})

test('delivery requires every backend field and a real boolean', () => {
  for (const patch of [
    { client_slots_sent: false }, { client_slots_sent: 'false' },
    { client_slots_email_id: '' }, { client_slots_email_id: ' ' },
    { slot_status: 'client_handoff_retry_pending' }, { slot_status: 'client_slot_send_failed' },
  ]) assert.equal(isClientHandoffDelivered({ ...delivered, ...patch }), false)
})

test('confirmed delivery completes handoff even while awaiting client selection', () => {
  assert.equal(isClientHandoffDelivered(delivered), true)
  assert.equal(pipelineStepComplete(3, 3, delivered), true)
  assert.equal(pipelineStepComplete(4, 3, delivered), false)
})

test('client slot confirmation preserves the completed handoff', () => {
  assert.equal(isClientHandoffDelivered({ ...delivered, slot_status: 'confirmed_by_client' }), true)
})

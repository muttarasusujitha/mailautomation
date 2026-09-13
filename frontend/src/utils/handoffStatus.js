export function isClientHandoffDelivered(trainer) {
  return trainer?.client_slots_sent === true &&
    Boolean(String(trainer?.client_slots_email_id || '').trim()) &&
    ['sent_to_client', 'confirmed_by_client'].includes(String(trainer?.slot_status || '').toLowerCase())
}

export function pipelineStepComplete(step, currentStep, trainer) {
  return step === 3 ? isClientHandoffDelivered(trainer) : step < currentStep
}

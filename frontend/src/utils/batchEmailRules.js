export function batchEmailRules(batchFlow) {
  if (batchFlow === 'proposal') {
    return 'Batch type: PROPOSAL. This is a prospective engagement, not confirmed training. Ask about interest and feasibility using only known scope. Keep unknown dates, budget and delivery arrangements tentative. Request or describe a TOC/lab estimate only when the reference requires it; call generated material proposed. Do not claim client approval, selection, an attached document, a booked interview, a PO or an invoice unless explicitly verified for the current stage.'
  }
  return 'Batch type: CONFIRMED REQUIREMENT. Use the agreed client scope and supplied schedule. Check trainer availability and delivery feasibility. Request missing profile information and three dated interview options at initial outreach. A confirmed requirement does not mean a selected trainer, booked interview, signed PO or paid invoice. Describe TOC/lab attachments only when verified; do not reopen agreed commercials or disclose internal margins.'
}

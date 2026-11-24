// The core API returns requirement fields at the top level. Older views also
// accept a nested requirement; expose the same shape to both billing pages.
export function normalizePipelineItem(item) {
  const requirement = item.requirement || item
  return {
    ...item,
    requirement,
    domain: item.domain || requirement.technology_needed || requirement.technology || 'Training',
    client: item.client || {
      name: requirement.client_name || requirement.client_company || '',
      company: requirement.client_company || requirement.client_name || '',
      email: requirement.client_email || '',
    },
  }
}

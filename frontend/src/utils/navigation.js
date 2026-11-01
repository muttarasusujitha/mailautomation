function normalizeNavigationText(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

export function resolveNavigationRoute(query, groups) {
  const normalizedQuery = normalizeNavigationText(query)
  if (!normalizedQuery) return null

  const items = (groups || []).flatMap(group => [
    ...(group.items || []),
    ...(group.more || []),
  ])
  const keywordsFor = item => (item.keywords || []).map(normalizeNavigationText).filter(Boolean)

  const exact = items.find(item => keywordsFor(item).includes(normalizedQuery))
  if (exact) return exact.to

  const matches = items.flatMap(item => keywordsFor(item)
    .filter(keyword => normalizedQuery.includes(keyword))
    .map(keyword => ({ item, keyword })))
    .sort((left, right) => right.keyword.length - left.keyword.length)

  return matches[0]?.item.to || null
}

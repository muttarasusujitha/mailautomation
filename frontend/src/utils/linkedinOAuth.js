export function parseLinkedInCallbackUrl(searchString) {
  const params = new URLSearchParams(searchString)
  return {
    code: params.get('code') || '',
    state: params.get('state') || '',
    error: params.get('error') || '',
    errorDescription: params.get('error_description') || '',
  }
}

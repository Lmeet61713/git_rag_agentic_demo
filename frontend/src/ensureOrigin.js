export function ensureCanonicalOrigin() {
  if (typeof window === 'undefined') return
  const url = new URL(window.location.href)
  if (url.hostname === 'localhost') {
    url.hostname = '127.0.0.1'
    window.location.replace(url.toString())
  }
}

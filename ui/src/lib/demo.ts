/**
 * Returns true when the URL contains ?demo=true.
 *
 * Kept as a separate module so tests can mock it and so AppShell doesn't
 * hard-code URL parsing inline. The result is stable for the lifetime of the
 * page (demo mode is set at load time, not toggled at runtime).
 *
 * Future: this module is also the right place to add `demoDataset` selection
 * once a demo dataset is available, so components remain decoupled from live
 * personal data during presentations.
 */
export function isDemoMode(): boolean {
  if (typeof window === 'undefined') return false;
  return new URLSearchParams(window.location.search).get('demo') === 'true';
}

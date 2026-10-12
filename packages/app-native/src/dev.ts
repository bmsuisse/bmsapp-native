// Shared by the helpers that warn about limits in development builds.

/** Development build: not a bundle with `NODE_ENV=production` / Vite's `PROD`. */
export function isDevelopment(): boolean {
  const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process
    ?.env
  if (env?.NODE_ENV === 'production') return false
  const meta = (import.meta as unknown as { env?: { PROD?: boolean } }).env
  return meta?.PROD !== true
}

export function warn(kind: string, warnings: string[]): void {
  if (typeof console === 'undefined') return
  for (const warning of warnings) console.warn(`[@bmsuisse/app-native] ${kind}: ${warning}`)
}

# AG Studio assumptions

- The installed documentation version is AG Studio 3.0.0. `AgStudioProvider` is used for the optional license key and AI module registration.
- The first integration uses Studio's built-in widgets for charts and grid, plus three custom read-only widgets. The custom widgets intentionally keep payment actions outside Studio's agent surface.
- Analytics amounts are numeric only at `/analytics/*` because AG Studio chart fields require numeric measures; the transactional dispute API continues to expose money as decimal strings.
- The local license key variable is `NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY`, matching the provider's client-side license requirement. It is optional in local development and must be supplied through `.env.local` for a licensed deployment.
- The current client keeps the existing drawer and simulator shell around the Studio canvas. This gives the Studio dashboard a stable application context while the remaining approval/settings routes are expanded.

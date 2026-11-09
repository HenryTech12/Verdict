# AG Studio assumptions

- The installed documentation version is AG Studio 3.0.0. `AgStudioProvider` is used for the optional license key and AI module registration.
- The first integration uses Studio's built-in widgets for charts and grid, plus three custom read-only widgets. The custom widgets intentionally keep payment actions outside Studio's agent surface.
- Analytics amounts are numeric only at `/analytics/*` because AG Studio chart fields require numeric measures; the transactional dispute API continues to expose money as decimal strings.
- The local license key variable is `NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY`, matching the provider's client-side license requirement. It is optional in local development and must be supplied through `.env.local` for a licensed deployment.
- The current client keeps the existing drawer and simulator shell around the Studio canvas. This gives the Studio dashboard a stable application context while the remaining approval/settings routes are expanded.

## Dispute table (AG Grid Community)

- The main dispute table uses AG Grid **Community**. Master/detail and row grouping are Enterprise features, so the expandable reasoning row is implemented with Community full-width rows, and status "grouping" is implemented as filter chips.
- Package versions are pinned by `package-lock.json` (`ag-studio` and `ag-studio-react` 3.0.0, `ag-grid-community` and `ag-grid-react` 36.2.0). Use `npm ci`, not `npm install`, because newer minor versions change the Studio types.

## AG Studio data model

* The lockfile pins `ag-studio` and `ag-studio-react` 3.0.0, where a relationship names its ends as `{ tableId, fieldId }` objects. Newer docs show the string form (`'order_items.product_id'`); if you upgrade, adjust `relationships` in `components/studio/model.ts`.
* Saved dashboards use the browser key `verdict.studio.state.v2`. Bump the version in `components/studio/state.ts` whenever the data model or default layout changes, so stale layouts are ignored.
* The dashboard opens in edit mode so the AI chat panel is visible. Whether the chat also appears in view mode has not been verified.

# Dashboard & Nav Structure

## Summary
The frontend nav and dashboard are driven by a single RPC (`dashboard.get` in `core/services/web_api.py`) that returns a **grouped** nav structure filtered by the caller's role and by which capabilities are actually running. Top-level groups are *Chat*, *Inbox*, *MCP*, *Security*, *System*. The UI splits this into two surfaces: `TopBar.tsx` runs across the top and renders the **top-level groups only** as a horizontal primary nav (with the right-side cluster — connection dot, `header.widgets` plugin slot, notification bell, avatar). `SideNav.tsx` is a **contextual left column** that renders either (a) a page-provided override via `usePageSidebar` (e.g. ChatPage's room list, InboxPage's mailbox folder list, plugin pages with their own nav) or (b) the children of whichever top-level group matches the current URL. When neither applies, the sidebar collapses away entirely so the main content gets full width.

## Details

### Backend — `_ws_dashboard_get`

Declares `nav_groups` as a list of dicts. Each group has:
- `key`, `label`, `description`, `icon`, `url` (default route when the group is clicked)
- `required_role` / `requires_capability` for the group itself
- `items` — list of child NavItems. Each item has label/description/icon/required_role/requires_capability plus **either** a `url` (navigation) or an `action` (RPC trigger; frontend shows a confirm dialog and invokes a named handler — e.g. `"restart_host"` calls `plugins.restart_host`). Empty items list = leaf group.

Filtering:
1. Each child's `requires_capability` is checked against the running service manager — if the service is missing or disabled, the child is dropped.
2. Each child's `required_role` is compared to `conn.user_level` via `AccessControlProvider.get_role_level`.
3. A non-leaf group whose every child is dropped disappears entirely.
4. A group's default `url` falls back to the first *visible* navigable child's URL if the hard-coded default is unreachable. Action items (no `url`) are skipped for this fallback — a group can't default-land on an RPC trigger.

The RPC returns both:
- `nav` — the filtered grouped structure (consumed by `SideNav`)
- `cards` — flat list of one card per visible top-level group, for the DashboardPage tile grid

### Frontend — `TopBar.tsx` + `SideNav.tsx` + `PageSidebar`

All three live under `frontend/src/components/layout/`. `AppShell.tsx` stacks `TopBar` above a row of `[SideNav, <Outlet />]`, with everything wrapped in `<PageSidebarProvider>`.

`TopBar.tsx`:
- Sticky top header running the full app width. Uses the same `useQuery(["dashboard", user_id])` as `SideNav`. **The user_id key is intentional** — it scopes the cache per-user so a login/logout swap refetches automatically (without it, the previous user's menu lingered until a manual refresh).
- **Desktop**: horizontal row of top-level groups (icon + label, `lg:` shows the label, smaller widths are icon-only). Clicking a group navigates to its default `url` — no popovers, no dropdowns. The active group gets a group-colored accent bar along its bottom edge. Right cluster: connection dot, `header.widgets` plugin slot, `NotificationBell`, avatar `DropdownMenu` (with `header.user-menu` plugin slot inside it).
- **Mobile**: hamburger opens a `Sheet` that renders the full hierarchy (top-level groups + nested children) since there's no room to split top + side. The hamburger also hosts the `restart_host` action confirm dialog.

`SideNav.tsx`:
- Hidden on mobile (`hidden md:flex`) — mobile uses the TopBar drawer for everything.
- Three-state render:
  1. If `usePageSidebarContent()` returns non-null, render the page-provided override and nothing else. Used by ChatPage (room list), InboxPage (mailbox list), and any plugin page that wants its own nav.
  2. Else, if a top-level group matches the URL via `isGroupActive` and it has children, render a section header (group icon + label) followed by the child link list. Active child gets a group-colored left accent bar.
  3. Else, return `null` — the sidebar disappears entirely and main content gets the full width.
- Mounts `<PluginPanelSlot slot="sidebar.bottom" />` at the foot whenever it's visible.

`PageSidebar.tsx` (the page-override primitive):
- `<PageSidebarProvider>` (mounted in `AppShell`) owns a single ReactNode override slot.
- `usePageSidebar(content)` is the hook pages call to publish their sidebar; it re-publishes on every render of the calling page (no dep array) so dynamic state (current selection, filters) stays in sync, and clears on unmount.
- `<PageSidebar>{children}</PageSidebar>` is the JSX-form shortcut (no children-in-place; the children are teleported to the global SideNav via context).
- Plugins import this via `@/components/layout/PageSidebar` like any core helper.
- **Two contexts, not one** (load-bearing!). The setter and the content live in separate contexts. The setter context's value is `useState`'s stable setter reference → never changes → pages that `useContext(SetContentContext)` *don't re-render* when content updates. The content context is what `SideNav` consumes. A single combined `{content, setContent}` context would re-render every page on every sidebar update — including the page that just called `setContent` from a no-deps `useEffect` — producing an infinite render loop that visibly froze navigation (clicking top-bar links did nothing because react-router's `Link` couldn't get a stable handler).

`isGroupActive(group, pathname)` is exported from `TopBar.tsx` and reused by `SideNav` for "which group matches the current route." It checks the group's own `url` and every child item's `url` (exact match or `pathname.startsWith(url + "/")`).

Icon mapping (`groupIconFor`) and the per-group color tables (`GROUP_COLORS`, `GROUP_ACCENT_BG`) live in `nav-shared.ts` so TopBar and SideNav share one source. Backend returns lucide icon names as strings (`"plug"`, `"shield"`, …) rather than forcing the frontend to know every route.

### Route structure (App.tsx)

```
/                       → DashboardPage
/chat                   → ChatPage
/inbox                  → InboxPage
/mcp                    → redirect to /mcp/servers
/mcp/servers            → McpPage (servers Gilbert connects to)
/mcp/clients            → McpClientsPage (bearer tokens for external clients)
/security               → redirect to /security/users
/security/*             → RolesPage (tabs: Users, Roles, Tools, AI Profiles, Collections, Events, RPC)
/settings               → SettingsPage
/scheduler              → SchedulerPage
/entities               → EntitiesPage
/plugins                → PluginsPage
/system                 → SystemPage (service inspector/browser)
```

The `/security/*` subroute replaces the old `/roles/*` paths. The RolesPage's index now redirects to `/security/users` (the default tab) rather than showing Roles first.

### MCP path collision note

The backend MCP HTTP endpoint is at **`/api/mcp`**, not `/mcp`, because the frontend SPA routes live under `/mcp/*`. Before this was sorted out, navigating to `/mcp` in the SPA worked on first click but a browser refresh returned `{"error": "unauthorized"}` — the starlette `/mcp` route beat the SPA fallback. Moving the backend to `/api/mcp` freed the `/mcp/*` namespace for the SPA and made browser refreshes on MCP pages work correctly.

## Related
- `src/gilbert/core/services/web_api.py` — `_ws_dashboard_get` grouped nav
- `frontend/src/types/dashboard.ts` — `DashboardResponse` / `NavGroup` / `NavItem` types
- `frontend/src/components/layout/TopBar.tsx` — horizontal primary nav (top-level groups) + right cluster + mobile drawer
- `frontend/src/components/layout/SideNav.tsx` — contextual left column: page override → group children → hidden
- `frontend/src/components/layout/PageSidebar.tsx` — context primitive that lets pages publish sidebar content (`usePageSidebar`)
- `frontend/src/components/layout/nav-shared.ts` — shared icon map + group color tables
- `frontend/src/components/layout/AppShell.tsx` — mounts the provider, TopBar, SideNav, `<Outlet />`
- `frontend/src/components/dashboard/DashboardPage.tsx` — tile grid from `cards`
- `frontend/src/components/roles/RolesPage.tsx` — /security/* tabs
- `frontend/src/App.tsx` — route table
- `memory-access-control.md` — the role filter behind `required_role`
- `memory-mcp.md` — why the backend MCP endpoint moved to `/api/mcp`

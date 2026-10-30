# Left Panel / Sidebar Component Structure

## Main Component: `AppLayout.tsx` (`webapp/src/features/layout/AppLayout.tsx`)

The left panel/sidebar is implemented using Mantine's `AppShellNavbar` component as the vertical navigation panel on the left side of the screen.

### Structure Overview

```
AppLayout
├── AppShell
│   ├── header (AppShellHeader) - top bar with Burger, title, palette, task indicator, theme toggle, user menu
│   ├── navbar (AppShellNavbar id="main-nav") - **LEFT SIDEBAR**
│   │   ├── Stack with NavLinks (scrollable)
│   │   │   ├── "Информационная панель" → /
│   │   │   ├── "База знаний" → /knowledge
│   │   │   ├── "Текущая сессия" → dynamic (currentSessionPath)
│   │   │   └── "Администрирование" → /admin (admin only)
│   │   └── bottom: system status + user profile/logout
│   └── main (AppShell.Main) - central content area
│       └── Suspense + RouteErrorBoundary + Outlet
│   └── CommandPalette (floating overlay)
└── TaskEventsProvider (context provider)
```

### Key Subcomponents

1. **`AppShellNavbar id="main-nav"`** (line 257)
   - `width: 260`, `breakpoint: 'sm'`
   - `collapsed: { mobile: !navOpened }`
   - Contains vertical `Stack` of navigation `NavLink` components
   - Scrollable with `overflowY: 'auto'`, `minHeight: 0`, `flex: 1`

2. **Navigation Items** (lines 176-191)
   ```typescript
   const items = [
     { to: '/', label: 'Информационная панель', enabled: true },
     { to: '/knowledge', label: 'База знаний', enabled: true },
     {
       to: currentSessionPath ?? '',
       label: 'Текущая сессия',
       enabled: currentSessionPath !== null,
     },
     ...(user?.role === 'admin' ? [{ to: '/admin', label: 'Администрирование', enabled: true }] : []),
   ]
   ```

3. **Responsive Behavior**
   - **Desktop** (`sm` and wider): Full sidebar visible (260px)
   - **Mobile** (`< sm`): Sidebar collapsed, revealed via Burger button
   - Burger toggles `navOpened` state
   - Navigation changes close the drawer automatically

4. **Header Integration** (AppShellHeader)
   - Left: Burger menu button + app title "boasi_s"
   - Center: Search palette trigger + task indicator + theme toggle
   - Right: User menu

5. **Bottom Section** (sidebar footer)
   - System status display
   - Divider separator
   - User profile with display name and role
   - Logout button (stuck to bottom via `marginTop: 'auto'`)

### Related Components

- **`TaskIndicator.tsx`** - Header component showing active task count with Popover detail view
- **`TaskPanel.tsx`** - Individual task progress display (used inside TaskIndicator Popover)
- **`UserMenu.tsx`** - User profile menu in header
- **`Burger`** - Hamburger toggle for sidebar collapse/expand
- **`SourceList.tsx`** - Displays answer sources (separate from sidebar, used in content area)
- **`CommandPalette.tsx`** - Search/floating palette overlay

### Design Notes

- No separate "Навигация" label - items are shown directly without extra heading
- Build date/footer removed per design decision ("шум, который занимает место и ничего не сообщает пользователю")
- Admin-only items conditionally rendered based on `user?.role === 'admin'`
- Current session item only shown when a session is actively open
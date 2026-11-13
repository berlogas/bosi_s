# Header Components with User Dropdown - Exploration Report

## Repository: N:/Development/boasi_s

### Components Found

#### 1. `PageHeader` (`webapp/src/components/PageHeader.tsx`)
- **Purpose**: Unified page header replacing fragmented `Title` + `Text` on each page
- **Key prop**: `actions?: React.ReactNode` — renders to the right of title/description
- **Structure**: 
  - Left: `Title` + optional `Text` (description)
  - Right: `actions` group with `Group gap="sm"`
- **Usage across repo**:
  - `DashboardPage.tsx`: shows greeting "Здравствуйте, {displayName(user)}!"
  - `AdminLayout.tsx`: title only, no actions
  - `AdminPageLegacy.tsx`: multiple usages
  - `KnowledgePage.tsx`: title + description

#### 2. `UserMenu` (`webapp/src/features/layout/UserMenu.tsx`)
- **Purpose**: User dropdown menu in thin header (Wave 2, p. 2)
- **Contents**:
  - Avatar with user name
  - Display name + role label (e.g., "Иван Иванов · researcher")
  - Menu item "Аккаунт" (disabled)
  - Divider
  - Menu item "Выйти" — triggers `logout()` → navigate to `/login`
- **Dependencies**: `@mantine/core` `Menu`, `Avatar`, `Button`; `@tabler/icons-react` `IconUserCircle`, `IconLogout`
- **Auth**: Uses `useAuth` from `features/auth/authStore`
- **Current placement**: Inside `AppLayout.tsx` `AppShellHeader` (line 253)

#### 3. Integration pattern (already partially established)
- `DashboardPage.tsx` uses `PageHeader` with `actions` prop containing simple text
- `UserMenu` could be placed in `PageHeader`'s `actions` position for a complete user dropdown on the right

### Design Observations

1. **Two parallel header systems exist**:
   - `PageHeader` — page-level header with right-side `actions` area
   - `AppLayout` + `UserMenu` — layout-level header with user menu in `AppShellHeader`

2. **`PageHeader` is more flexible for right-side placement** since it has a dedicated `actions` prop designed for buttons, selectors, etc.

3. **`UserMenu` is tightly coupled to layout/auth state** but could be reused inside `PageHeader.actions`

4. **No component currently combines both patterns** — no `PageHeader` usage includes `UserMenu` in its `actions`

### Potential Integration

To create a header component with user dropdown on the right side, one could place `<UserMenu />` inside `PageHeader`'s `actions` prop:

```tsx
<PageHeader
  title="Some Page"
  actions={<UserMenu />}
/>
```

This would render the user menu (avatar, name, role, logout) on the right side of the header, leveraging `PageHeader`'s existing right-aligned actions layout.

### Files Explored
- `webapp/src/components/PageHeader.tsx`
- `webapp/src/features/layout/UserMenu.tsx`
- `webapp/src/features/layout/AppLayout.tsx` (UserMenu usage at line 253)
- `webapp/src/features/dashboard/DashboardPage.tsx` (PageHeader with actions)
- `webapp/src/features/admin/AdminLayout.tsx` (PageHeader without actions)
- `webapp/src/features/admin/AdminPageLegacy.tsx` (PageHeader usages)
- `webapp/src/features/knowledge/KnowledgePage.tsx` (PageHeader usage)
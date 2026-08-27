# EnterpriseAI Web (`apps/web` → `/web`)

Next.js (App Router) + TypeScript frontend for the EnterpriseAI auth service:
one **login / signup** screen and **three separate dashboards** based on role —

| Role | Dashboard route |
| :--- | :-------------- |
| `vendor_admin` | `/vendor` |
| `tenant_admin` | `/tenant` |
| `tenant_user` | `/user` |

## Stack

| Layer | Tech |
| :--- | :--- |
| Framework | Next.js 15 (App Router) + TypeScript |
| UI | Tailwind CSS v4 + shadcn-style components (`components/ui`) |
| Forms | React Hook Form + Zod |
| State | Zustand (persisted auth store) |
| Server/API data | TanStack Query |
| Icons | Lucide |
| Testing | Vitest |

## Getting started

```bash
cd web
pnpm install
cp .env.example .env        # point NEXT_PUBLIC_API_URL at your backend
pnpm dev                    # http://localhost:3000/auth
```

Production:

```bash
pnpm build && pnpm start
```

> Note: `NEXT_PUBLIC_API_URL` is inlined at **build** time for `pnpm build`;
> restart `pnpm dev` after changing `.env`.

## Flow

1. `/auth` — tabbed Login / Sign up card.
   - Signup picks a **role** (Vendor Admin / Tenant Admin / Tenant User) and a
     tenant name; Zod validates everything client-side.
2. On success the tokens + account are stored (Zustand + localStorage) and the
   app redirects to the dashboard matching the returned `user.role`
   (`dashboardPathForRole()`).
3. Each dashboard is wrapped in `ProtectedDashboard`, which checks the stored
   account's role against the page's required role:
   - not logged in → redirect to `/auth`
   - wrong role → "Access denied" screen
4. Backend enforcement mirrors this: `/api/v1/dashboard/*` returns **403**
   unless the JWT's `role` claim matches.

## Test backend connection

```bash
curl -X POST http://localhost:8001/api/v1/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@acme.com","password":"Secret12345","full_name":"Admin","role":"tenant_admin","tenant_name":"Acme"}'
```

## Tests

```bash
pnpm test     # Vitest: role↔route mapping + zod schemas
```

## Layout

```
web/
├── app/
│   ├── auth/page.tsx         # login + signup card
│   ├── vendor/page.tsx       # vendor dashboard (guarded)
│   ├── tenant/page.tsx       # tenant dashboard (guarded)
│   └── user/page.tsx         # tenant-user dashboard (guarded)
├── components/
│   ├── login-form.tsx / signup-form.tsx
│   ├── protected-dashboard.tsx
│   ├── providers.tsx         # TanStack Query provider
│   └── ui/                   # button, input, card, label, alert, spinner
├── lib/
│   ├── api.ts                # typed fetch client (Bearer token)
│   ├── validations.ts        # zod schemas, ROLES map, role→route helpers
│   └── utils.ts              # cn()
├── stores/auth-store.ts      # zustand persisted session
└── tests/                    # vitest specs
```
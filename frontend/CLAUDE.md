# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

## Project state

Frontend for the Accelerise legal-document RAG app. Built so far: Cognito login/register/confirm pages, a dashboard with chat history, Chat (answers with citations and a collapsible list of all retrieved sources), Documents panels and a PDF/image viewer that opens cited passages highlighted (other dashboard sections are "Soon" placeholders), and a `/profile` page. Tenant/organization handling is deliberately out of scope for now. "Casefile" is a placeholder product name.

## Architecture

- **Auth is entirely client-side via Amplify** (`aws-amplify/auth`): tokens live in browser storage, so there is no server-side session, no `proxy.ts`, and route protection is a client check (`components/use-current-user.ts` redirects to `/login`; `use-redirect-if-signed-in.ts` does the reverse on auth pages). Amplify is configured once at module load in `components/amplify-config.tsx`, rendered from the root layout.
- Users sign in by email (`username` = email). Sign-up requires `email`, `given_name`, `family_name`; register uses `autoSignIn`, so confirming the code in the same tab lands on the dashboard. Unconfirmed users who sign in are sent to `/confirm?email=…` with a fresh code.
- **The browser calls FastAPI directly** (`NEXT_PUBLIC_API_URL`, default `http://127.0.0.1:8000`) with `Authorization: Bearer <access token>`; see `lib/api.ts`. The endpoint contract the backend must implement is in `docs/backend-api.md` — update both together. Failed list calls render the empty state rather than an error.
- **The open conversation and document view live in the URL** (`/?c=<id>&doc=<id>&page=<n>&passage=<chunk id>`; never the presigned file URL), read with `useSearchParams` (hence the `Suspense` in `app/page.tsx`) and changed with `window.history.pushState`/`replaceState`, which Next syncs into `useSearchParams`. `ChatPanel` is keyed so it remounts when the URL moves to another conversation, but a new chat adopting the id from its first answer keeps the panel (see `panel` in `components/dashboard/dashboard.tsx`).
- Auth pages share the split layout in `app/(auth)/layout.tsx`; the dashboard is `app/page.tsx` → `components/dashboard/`; `/profile` edits Cognito attributes (Amplify `updateUserAttributes` / `deleteUserAttributes` for cleared optional fields) and shows usage computed from `GET /documents` — the backend has no profile endpoint. Pages kept mounted in the background refresh the user via the `announceProfileUpdated()` window event.

## Local Cognito (Floci)

Env vars are documented in `.env.example` (copy to `.env.local`). Locally Cognito is emulated by Floci at `http://localhost.floci.io:4566`.

- Floci doesn't answer CORS preflight, so the browser uses `NEXT_PUBLIC_COGNITO_ENDPOINT=http://localhost:3000/cognito` and `next.config.ts` rewrites `/cognito` to `COGNITO_DEV_PROXY_TARGET`. Unset both to hit real Cognito.
- Confirmation emails aren't delivered; read codes from `http://localhost.floci.io:4566/_aws/ses` (JSON list of sent messages).
- The app client only allows `USER_SRP_AUTH` + refresh (no `USER_PASSWORD_AUTH`). Floci requires the `Session` value echoed on the SRP `RespondToAuthChallenge`, which Amplify does.
- Floci-issued tokens have `iss: http://localhost:4566/<pool id>`.

## Commands

- `npm run dev` — dev server on http://localhost:3000 (Turbopack)
- `npm run build` — production build; also the type-check gate (`tsconfig` has `noEmit`, no separate `tsc` script)
- `npm run start` — serve the production build
- `npm run lint` — runs `eslint` directly (flat config in `eslint.config.mjs`), not `next lint`; lint one file with `npx eslint app/page.tsx`

No test runner is configured. With Cache Components, Next 16 keeps recently visited routes mounted but hidden, so browser-automation selectors must filter to visible elements; Next's route announcer also has `role="alert"`.

## Stack and non-default config

- Next.js 16.4.2, React 19.3, TypeScript strict, App Router only (`app/`). The Next version is newer than most training data — check `node_modules/next/dist/docs/` (`01-app/`, `03-architecture/`) before using an API.
- `next.config.ts` enables `cacheComponents` and `partialPrefetching`. With Cache Components on, data fetching and caching use `"use cache"` + `cacheLife` with Suspense; route segment configs `dynamic`, `revalidate`, `fetchCache` don't apply and `dynamicParams` is incompatible. See `01-app/01-getting-started/08-caching.md` in the bundled docs before adding data fetching.
- `experimental.agentFeedback` is on; `next dev` rewrites the `AGENTS.md` block automatically.
- Tailwind CSS v4 is wired through a Turbopack loader rule (`@tailwindcss/turbopack` on `*.css`) — there is no `postcss.config` or `tailwind.config`. Theme tokens live in `app/globals.css` under `@theme inline`, with light/dark values switched by `prefers-color-scheme`.
- Layouts/pages use Next's generated global route types (e.g. `LayoutProps<"/">`), produced into `.next/types` during dev/build.
- Path alias `@/*` maps to the repo root.
- Fonts: Public Sans (UI, `font-sans`) and Source Serif 4 (headings, answers, quotes, `font-serif`) via `next/font/google`. Color tokens (`paper`, `surface`, `ink`, `muted`, `rule`, `brand`, `highlight`, `danger`, `ok`) and `shadow-pop` are defined in `app/globals.css`; icons are inline SVGs in `components/icons.tsx` (no icon package); the `.highlight` class renders cited passages as highlighter marks.

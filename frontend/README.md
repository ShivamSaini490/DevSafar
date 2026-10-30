# DevSafar Frontend

React, TypeScript, Vite and Tailwind CSS frontend for the DevSafar AI travel planner. The specs live in `/docs`.

## Run it

```bash
npm install
cp .env.example .env.local
npm run dev
```

The dev server proxies `/api` to the FastAPI backend (`VITE_DEV_PROXY_TARGET`, default `http://127.0.0.1:8000`).
The backend has no CORS middleware, so the browser must reach both on one origin. That keeps the HttpOnly auth
cookie and the CSRF cookie working. Serve them on one origin in production too.

## Scripts

| Command | Purpose |
| --- | --- |
| `npm run dev` | Start the dev server |
| `npm run build` | Typecheck and build for production |
| `npm test` | Run unit tests |
| `npm run lint` | ESLint. Currently fails to start, see below |

`typescript-eslint` does not support TypeScript 7 yet, so `npm run lint` exits with an error, and `.npmrc` sets
`legacy-peer-deps` for the same conflict. Remove both limits once `typescript-eslint` supports TS 7.

## What exists today

| Route | Status |
| --- | --- |
| `/` | Landing page |
| `/chat?mode=temporary` | Working full-screen temporary chat, for guests and signed-in users |
| `/login`, `/signup` | Working, wired to the auth API |
| `/forgot-password` | Placeholder until the OTP recovery module |
| Saved chats, `/chat/:id`, `/settings` | Not built yet |

## API used so far

| Endpoint | Used by |
| --- | --- |
| `POST /api/v1/auth/signup` | Sign up, followed by login because signup sets no cookie |
| `POST /api/v1/auth/login` | Sign in |
| `POST /api/v1/auth/logout` | Header, sends `X-CSRF-Token` |
| `GET /api/v1/users/me` | Header, only when the CSRF cookie exists |
| `POST /api/v1/chat/temporary` | Chat page |

All calls go through `src/services/apiClient.ts`.

## Rules for this code

- Temporary chat stays in React memory. Never put it in localStorage or a persisted store.
- Rupee figures on the landing page are the blueprint's samples and always carry a sample label. Never show them as live.
- Scroll pinning runs through `gsap.matchMedia`, so phones and reduced-motion users get a normal static page.
- Secret keys never belong in the frontend. Every `VITE_` variable ships to the browser.

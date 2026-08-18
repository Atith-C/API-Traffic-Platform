# Frontend — API Traffic Platform Dashboard

A minimal React + TypeScript + Vite + Tailwind + React Query dashboard for the platform. It is
intentionally lean — the platform's focus is the backend — but it is a real, working SPA:

- **Login** (`/auth/login`) — stores the access token and shows the dashboard.
- **Developer dashboard** — org switcher, headline stats (requests, errors, error rate, avg/p95
  latency, active keys), top endpoints, and a status-code breakdown. Auto-refreshes every 15s.

## Run

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173  (proxies /api -> http://localhost:8000)
```

Have the backend running (`uvicorn app.main:app` or the docker-compose stack) first.

## Build / typecheck

```bash
npm run build      # tsc -b + vite build
npm run lint       # tsc --noEmit
```

## Notes

- API calls go through the Vite dev proxy (`/api` → backend), so the SPA and API share an origin in
  development. In production, serve the built assets behind the same reverse proxy as the API.
- Token handling here is deliberately simple (localStorage) for the demo. The backend also sets an
  httpOnly refresh cookie; a production SPA would use silent refresh via `/auth/refresh`.

# QB Auditor — Frontend

Next.js 14 + Clerk + Tailwind. Talks to the FastAPI backend in `../backend`.

## Setup

```bash
cd frontend
npm install
cp .env.local.example .env.local
# Fill in Clerk keys from https://dashboard.clerk.com
```

## Run

Backend first (in a separate terminal from the repo root):
```bash
venv/bin/uvicorn backend.main:app --reload --port 8001
```

Then frontend:
```bash
npm run dev
```

Open http://localhost:3000

## Env vars

- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` — from Clerk dashboard
- `CLERK_SECRET_KEY` — from Clerk dashboard
- `NEXT_PUBLIC_API_URL` — backend URL (default `http://localhost:8001`)

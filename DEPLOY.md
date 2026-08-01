# Deploy guide

Backend → Fly.io (SQLite on a persistent volume, litestream backups to S3).
Frontend → Vercel.

## Backend on Fly.io

### 1. Install flyctl and sign up
```bash
brew install flyctl
fly auth signup    # opens browser, credit card needed but no charge on free tier
```

### 2. Launch the app (first time only)
From the repo root:
```bash
fly launch --no-deploy   # accept defaults; app name from fly.toml
```

### 3. Create the persistent volume
```bash
fly volumes create qb_auditor_data --region iad --size 1
```

### 4. Set secrets (env vars)
```bash
fly secrets set \
  QBO_CLIENT_ID=... \
  QBO_CLIENT_SECRET=... \
  QBO_ENVIRONMENT=sandbox \
  MS_CLIENT_ID=... \
  MS_CLIENT_SECRET=... \
  MS_TENANT_ID=common \
  ANTHROPIC_API_KEY=... \
  CLERK_PUBLISHABLE_KEY=pk_test_... \
  BACKEND_URL=https://qb-auditor-backend.fly.dev \
  FRONTEND_URL=https://your-vercel-app.vercel.app \
  RECEIPTS_FROM=...

# Litestream backups (optional; skip these to run without backups)
fly secrets set \
  LITESTREAM_REPLICA_URL=s3://your-bucket/qb-auditor \
  LITESTREAM_ACCESS_KEY_ID=... \
  LITESTREAM_SECRET_ACCESS_KEY=...
```

### 5. Deploy
```bash
fly deploy
```

### 6. Update OAuth redirect URIs
Intuit dev portal → add `https://qb-auditor-backend.fly.dev/oauth/qbo/callback`
Azure app registration → add `https://qb-auditor-backend.fly.dev/oauth/outlook/callback`

## Frontend on Vercel

### 1. Push to GitHub (already done for the repo)

### 2. Import project
- vercel.com → New Project → import from GitHub
- Root directory: `frontend/`
- Framework preset: Next.js

### 3. Set env vars in Vercel
- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` — same as Clerk dashboard
- `CLERK_SECRET_KEY` — same as Clerk dashboard
- `NEXT_PUBLIC_API_URL` — `https://qb-auditor-backend.fly.dev`

### 4. Deploy
Vercel auto-deploys on push to `main`.

### 5. Update Clerk allowed origins
Clerk dashboard → Domains → add your Vercel URL.

## Verify

- Open `https://your-vercel-app.vercel.app`
- Sign up → land on dashboard
- Add a client → connect QBO and Outlook via browser → should redirect through the fly backend and back to your Vercel frontend

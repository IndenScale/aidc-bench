# AIDC-Bench Cloudflare Deployment (Workers + Static Assets + D1 + R2)

AIDC-Bench's official website and leaderboard database run independently on **Cloudflare Workers Static Assets + D1 + R2** with zero Harbor Hub dependency.

## Architecture

- **Static SPA (`env.ASSETS`)**: Serves the compiled `../dashboard/` Vite output with SPA fallback for `/tasks`, `/run`, `/rows/...`, etc.
- **Database (`env.DB`, Cloudflare D1 / SQLite)**: Stores `suites`, `tasks`, `runs`, `trials`, `audit_checks`, and `dashboard_snapshots`, with a `visibility` (`public` | `private`) column so public and private benchmark suites share one schema.
- **Artifact Storage (`env.ARTIFACTS`, Cloudflare R2)**: Stores full dashboard snapshots and per-agent trial bundles (`agent.log`, verifier outputs, submissions, 4FZ7 layouts) with zero egress fees.

## First-Time Setup

```bash
# 1. Build the frontend bundle into ../dashboard/
bun run --cwd ../web build

# 2. Install Wrangler & regenerate exact binding types
cd cloudflare
bun install
bun run cf-typegen

# 3. Create Cloudflare D1 database & R2 bucket (one-time)
bunx wrangler login
bunx wrangler d1 create aidc-bench-db
# -> Copy the returned database_id into wrangler.jsonc
bunx wrangler r2 bucket create aidc-bench-artifacts

# 4. Apply D1 SQL schema & configure publish secret
bun run db:migrate:remote
bunx wrangler secret put PUBLISH_API_TOKEN

# 5. Deploy Workers + Static Assets + API
bun run deploy
```

## Switching Frontend to API Mode

By default, `web/` reads `/data/dashboard.json` and `/data/trials/<slug>.json` from static assets (works offline, on Vite dev, and on Workers Static Assets immediately).

To have the SPA query the D1/R2 Workers API (with automatic static fallback):

```bash
VITE_API_BASE=/api bun run --cwd ../web build
bun run --cwd . deploy
```

## GitHub Push Auto-Deploy (Cloudflare Workers Builds + D1 Sync)

Connect `IndenScale/aidc-bench` in **Cloudflare Dashboard → Workers & Pages → `aidc-bench` → Settings → Build**:

- **Root directory**: `cloudflare`
- **Production branch**: `main`
- **Build command**: `bun run build:ci`
- **Deploy command**: `bun run deploy:ci` (runs D1 migrations, regenerates & applies `seed_public_v1.sql`, then deploys Worker + Static Assets)
- **Non-production branch / Preview command**: `bun run preview:ci` (uploads preview version without mutating production D1)
- **Build watch paths (Include)**: `web/**`, `cloudflare/**`
- **API token permissions**: Cloudflare's auto-generated Workers Builds token does **not** include D1 write permission by default. Edit the Workers Builds user token in **My Profile → API Tokens** and add **Account → D1 → Edit**.

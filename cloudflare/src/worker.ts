/**
 * AIDC-Bench Cloudflare Worker:
 * - Serves the Vite SPA via Workers Static Assets (`env.ASSETS`)
 * - Exposes `/api/v1/*` backed by D1 (SQLite metadata) + R2 (dashboard snapshots & trial bundles)
 * - Falls back seamlessly to static `/data/*.json` before D1/R2 are seeded
 */

const SAFE_SLUG_RE = /^[a-zA-Z0-9._-]+$/;

function jsonResponse(body: unknown, status = 200, cacheControl = "no-store"): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": cacheControl,
    },
  });
}

/** Constant-time token comparison via SHA-256 + Web Crypto timingSafeEqual. */
async function verifyBearerToken(authHeader: string | null, expectedSecret: string | undefined): Promise<boolean> {
  if (!authHeader || !expectedSecret) return false;
  const prefix = "Bearer ";
  if (!authHeader.startsWith(prefix)) return false;
  const provided = authHeader.slice(prefix.length).trim();
  if (!provided) return false;

  const enc = new TextEncoder();
  const [hashA, hashB] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(provided)),
    crypto.subtle.digest("SHA-256", enc.encode(expectedSecret)),
  ]);
  const a = new Uint8Array(hashA);
  const b = new Uint8Array(hashB);
  if (a.byteLength !== b.byteLength) return false;

  let diff = 0;
  for (let i = 0; i < a.byteLength; i++) {
    diff |= a[i] ^ b[i];
  }
  return diff === 0;
}

async function handleGetDashboard(request: Request, env: Env): Promise<Response> {
  if (env.ARTIFACTS) {
    try {
      const row = await env.DB.prepare(
        "SELECT payload_r2_key FROM dashboard_snapshots WHERE suite_id = ?1 AND visibility = 'public' LIMIT 1",
      )
        .bind("public_v1")
        .first<{ payload_r2_key: string }>();

      if (row?.payload_r2_key) {
        const obj = await env.ARTIFACTS.get(row.payload_r2_key);
        if (obj) {
          return new Response(obj.body, {
            status: 200,
            headers: {
              "content-type": "application/json; charset=utf-8",
              "cache-control": "public, max-age=60",
              "x-aidc-source": "r2-snapshot",
            },
          });
        }
      }
    } catch (err) {
      console.error(
        JSON.stringify({
          message: "d1_or_r2_dashboard_fallback",
          error: err instanceof Error ? err.message : String(err),
        }),
      );
    }
  }

  // Fallback to static asset bundle until D1/R2 snapshot is published
  const staticUrl = new URL("/data/dashboard.json", request.url);
  return env.ASSETS.fetch(new Request(staticUrl.toString(), { method: "GET" }));
}

async function handleGetTrials(request: Request, env: Env, slug: string): Promise<Response> {
  if (!SAFE_SLUG_RE.test(slug)) {
    return jsonResponse({ error: "invalid-slug" }, 400);
  }

  if (env.ARTIFACTS) {
    try {
      const obj = await env.ARTIFACTS.get(`trials/public_v1/${slug}.json`);
      if (obj) {
        return new Response(obj.body, {
          status: 200,
          headers: {
            "content-type": "application/json; charset=utf-8",
            "cache-control": "public, max-age=300",
            "x-aidc-source": "r2-artifact",
          },
        });
      }
    } catch (err) {
      console.error(
        JSON.stringify({
          message: "r2_trial_fallback",
          slug,
          error: err instanceof Error ? err.message : String(err),
        }),
      );
    }
  }

  const staticUrl = new URL(`/data/trials/${encodeURIComponent(slug)}.json`, request.url);
  return env.ASSETS.fetch(new Request(staticUrl.toString(), { method: "GET" }));
}

async function handleListRuns(env: Env, url: URL): Promise<Response> {
  const suiteId = url.searchParams.get("suite") || "public_v1";
  const result = await env.DB.prepare(
    `SELECT run_id, suite_id, slug, model_name, agent_harness, runner_kind,
            is_reference, n_trials, mean_total_800, std_total_800,
            pass_at_1_pct, pass_at_1_ci95_pct, pass_at_k_pct, pass_pow_k_pct,
            mean_soft_score, mean_regret_pct, mean_credits_pct, mean_task_sec,
            verified, created_at
       FROM runs
      WHERE suite_id = ?1 AND visibility = 'public'
      ORDER BY mean_total_800 DESC`,
  )
    .bind(suiteId)
    .all();

  return jsonResponse({ suite_id: suiteId, runs: result.results }, 200, "public, max-age=30");
}

async function handlePublish(request: Request, env: Env, url: URL): Promise<Response> {
  const authed = await verifyBearerToken(request.headers.get("authorization"), env.PUBLISH_API_TOKEN);
  if (!authed) {
    return jsonResponse({ error: "unauthorized" }, 401);
  }
  if (!env.ARTIFACTS) {
    return jsonResponse({ error: "r2-not-configured", hint: "Enable R2 and bind ARTIFACTS in wrangler.jsonc" }, 503);
  }

  const kind = url.searchParams.get("kind") || "dashboard";
  const suiteId = url.searchParams.get("suite") || "public_v1";

  if (kind === "dashboard") {
    if (!request.body) return jsonResponse({ error: "missing-body" }, 400);
    const r2Key = `snapshots/${suiteId}/dashboard.json`;
    await env.ARTIFACTS.put(r2Key, request.body, {
      httpMetadata: { contentType: "application/json; charset=utf-8" },
    });
    await env.DB.prepare(
      `INSERT INTO dashboard_snapshots (suite_id, visibility, payload_r2_key, updated_at)
       VALUES (?1, 'public', ?2, datetime('now'))
       ON CONFLICT(suite_id, visibility)
       DO UPDATE SET payload_r2_key = excluded.payload_r2_key, updated_at = datetime('now')`,
    )
      .bind(suiteId, r2Key)
      .run();

    console.log(JSON.stringify({ message: "published_dashboard_snapshot", suite_id: suiteId, r2_key: r2Key }));
    return jsonResponse({ ok: true, kind, suite_id: suiteId, r2_key: r2Key });
  }

  if (kind === "trials") {
    const slug = url.searchParams.get("slug") || "";
    if (!SAFE_SLUG_RE.test(slug)) return jsonResponse({ error: "invalid-slug" }, 400);
    if (!request.body) return jsonResponse({ error: "missing-body" }, 400);
    const r2Key = `trials/${suiteId}/${slug}.json`;
    await env.ARTIFACTS.put(r2Key, request.body, {
      httpMetadata: { contentType: "application/json; charset=utf-8" },
    });

    console.log(JSON.stringify({ message: "published_trial_bundle", suite_id: suiteId, slug, r2_key: r2Key }));
    return jsonResponse({ ok: true, kind, suite_id: suiteId, slug, r2_key: r2Key });
  }

  return jsonResponse({ error: "unsupported-kind" }, 400);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    if (path === "/api/v1/health" && request.method === "GET") {
      let dbOk = false;
      let runsCount = 0;
      let tasksCount = 0;
      try {
        const [rRow, tRow] = await Promise.all([
          env.DB.prepare("SELECT COUNT(*) AS cnt FROM runs WHERE visibility = 'public'").first<{ cnt: number }>(),
          env.DB.prepare("SELECT COUNT(*) AS cnt FROM tasks WHERE visibility = 'public'").first<{ cnt: number }>(),
        ]);
        dbOk = true;
        runsCount = Number(rRow?.cnt ?? 0);
        tasksCount = Number(tRow?.cnt ?? 0);
      } catch (err) {
        console.error(JSON.stringify({ message: "health_d1_error", error: err instanceof Error ? err.message : String(err) }));
      }
      return jsonResponse({
        status: "ok",
        service: "aidc-bench",
        db_ok: dbOk,
        r2_enabled: Boolean(env.ARTIFACTS),
        public_tasks: tasksCount,
        public_runs: runsCount,
      });
    }

    if (path === "/api/v1/dashboard" && request.method === "GET") {
      return handleGetDashboard(request, env);
    }

    if (path.startsWith("/api/v1/trials/") && request.method === "GET") {
      const slug = decodeURIComponent(path.slice("/api/v1/trials/".length));
      return handleGetTrials(request, env, slug);
    }

    if (path === "/api/v1/runs" && request.method === "GET") {
      return handleListRuns(env, url);
    }

    if (path === "/api/v1/publish" && request.method === "POST") {
      return handlePublish(request, env, url);
    }

    if (path.startsWith("/api/")) {
      return jsonResponse({ error: "not-found", path }, 404);
    }

    return env.ASSETS.fetch(request);
  },
} satisfies ExportedHandler<Env>;

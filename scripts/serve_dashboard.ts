import { resolve, normalize } from "node:path";

const PORT = Number(process.env.PORT ?? 8765);
const HOST = process.env.HOST ?? "127.0.0.1";
const ROOT = resolve(import.meta.dir, "..", "dashboard");

const server = Bun.serve({
  hostname: HOST,
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);
    const rawPath = decodeURIComponent(url.pathname === "/" ? "/index.html" : url.pathname);
    const safeRel = normalize(rawPath).replace(/^(\.\.[/\\])+/, "").replace(/^[/\\]+/, "");
    const targetPath = resolve(ROOT, safeRel);

    if (!targetPath.startsWith(ROOT)) {
      return new Response("Forbidden", { status: 403 });
    }

    const file = Bun.file(targetPath);
    if (await file.exists()) {
      return new Response(file, {
        headers: { "Cache-Control": "no-store" },
      });
    }

    // SPA History API fallback for clean routes (/run, /tasks, /rows/..., etc.)
    if (!url.pathname.startsWith("/data/") && !url.pathname.startsWith("/assets/")) {
      const indexFile = Bun.file(resolve(ROOT, "index.html"));
      if (await indexFile.exists()) {
        return new Response(indexFile, {
          headers: { "Cache-Control": "no-store" },
        });
      }
    }

    return new Response("Not Found", { status: 404 });
  },
});

console.log(`AIDC-Bench production preview serving ${ROOT} at http://${server.hostname}:${server.port}/`);

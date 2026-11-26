import "./styles.css";
import type { DashboardPayload } from "./types";
import { mountApp } from "./app";
import { loadDashboardPayload } from "./dataProvider";

let cleanup: (() => void) | null = null;

async function start(cachedPayload?: DashboardPayload): Promise<void> {
  const payload = cachedPayload ?? (await loadDashboardPayload());

  cleanup?.();
  cleanup = mountApp(payload);

  if (import.meta.hot) {
    import.meta.hot.data.payload = payload;
  }
}

start(import.meta.hot?.data?.payload as DashboardPayload | undefined).catch((err) => {
  console.error(err);
  const app = document.getElementById("app");
  if (app) {
    app.innerHTML = `<div class="container" style="padding:40px 0;color:var(--text-muted)">Failed to load benchmark dataset: ${String(err)}</div>`;
  }
});

if (import.meta.hot) {
  import.meta.hot.accept(["./app"], async (mods) => {
    const mod = mods[0] as typeof import("./app") | undefined;
    if (!mod) return;
    const payload = import.meta.hot?.data?.payload as DashboardPayload | undefined;
    if (payload) {
      cleanup?.();
      cleanup = mod.mountApp(payload);
    }
  });
  import.meta.hot.dispose(() => {
    cleanup?.();
    cleanup = null;
  });
}

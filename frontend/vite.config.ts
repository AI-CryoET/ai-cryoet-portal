import { readFileSync } from "node:fs";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import { defineConfig, loadEnv } from "vite";
import viteReact from "@vitejs/plugin-react";

/// <reference types="vitest" />

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.API_PROXY_TARGET || "http://localhost:8000";
  // SSR-side fetches read process.env.CRYOET_API_BASE_URL; mirror API_PROXY_TARGET into it
  // so a single .env.local var configures both the browser proxy and the SSR base URL.
  process.env.CRYOET_API_BASE_URL ??= apiTarget;

  // Optional HTTPS for the dev server. Enabled only when both cert env vars are
  // set (e.g. via .env.local); plain HTTP otherwise, so normal `npm run dev` is
  // unchanged. Serving over a *.janelia.org origin lets the browser attach
  // Fileglancer's same-site session cookie so the "Save to file share" write can
  // be tested locally. Local-only convenience — not needed for prod.
  const sslCert = env.FRONTEND_SSL_CERT;
  const sslKey = env.FRONTEND_SSL_KEY;
  const https =
    sslCert && sslKey
      ? { cert: readFileSync(sslCert), key: readFileSync(sslKey) }
      : undefined;

  // ---------------------------------------------------------------------------
  // DEV-ONLY reverse proxy for in-process Neuroglancer.
  //
  // IMPORTANT: this proxy ONLY exists in the Vite dev server. In production
  // (the built/`srvx` server, Docker, etc.) Neuroglancer is reached directly on
  // its own port — `docker-compose.yml` maps 8050:8050 — so none of this runs.
  // If you ever want prod parity behind a single ingress, replicate this prefix
  // proxying in nginx / the prod server instead.
  //
  // The proxied prefixes are Neuroglancer's fixed root paths (from its Tornado
  // route table): viewer app + bundles (/v), volume info & data chunks
  // (/neuroglancer), the long-lived state event stream (/events, SSE), and the
  // state/action/response/credentials channels.
  const ngTarget =
    env.NEUROGLANCER_PROXY_TARGET ||
    `http://127.0.0.1:${env.NEUROGLANCER_PORT || 8050}`;
  const ngPaths = [
    "/v",
    "/neuroglancer",
    "/events",
    "/state",
    "/action",
    "/volume_response",
    "/credentials",
  ];
  const neuroglancerDevProxy = Object.fromEntries(
    ngPaths.map((p) => [`^${p}/`, { target: ngTarget, ws: true }]),
  );

  return {
    server: {
      port: Number(env.FRONTEND_PORT) || 3000,
      host: true,
      // When serving HTTPS on a custom hostname, Vite 8 rejects Host headers not
      // in this allowlist; scope it to the internal Janelia domain. Only applied
      // alongside the cert so plain-HTTP dev is untouched.
      ...(https ? { https, allowedHosts: [".int.janelia.org"] } : {}),
      proxy: {
        "/api": {
          target: apiTarget,
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/api/, ""),
        },
        // DEV-ONLY: Neuroglancer reverse proxy (see comment above). Not present
        // in any production build.
        ...neuroglancerDevProxy,
      },
    },
    ssr: {
      noExternal: ["@mui/*"],
    },
    resolve: {
      tsconfigPaths: true,
    },
    plugins: [tanstackStart(), viteReact()],
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test-setup.ts"],
    },
  };
});

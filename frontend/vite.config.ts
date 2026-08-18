import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { tanstackStart } from '@tanstack/react-start/plugin/vite';
import { defineConfig, loadEnv } from 'vite';
import viteReact from '@vitejs/plugin-react';

/// <reference types="vitest" />

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiTarget = env.API_PROXY_TARGET || 'http://localhost:8000';
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

  return {
    server: {
      port: Number(env.FRONTEND_PORT) || 3000,
      host: true,
      // When serving HTTPS on a custom hostname, Vite 8 rejects Host headers not
      // in this allowlist; scope it to the internal Janelia domain. Only applied
      // alongside the cert so plain-HTTP dev is untouched.
      ...(https ? { https, allowedHosts: ['.int.janelia.org'] } : {}),
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          rewrite: p => p.replace(/^\/api/, '')
        }
      }
    },
    ssr: {
      noExternal: ['@mui/*']
    },
    resolve: {
      tsconfigPaths: true,
      // Vite's native tsconfigPaths resolution only aliases files matched by
      // tsconfig.json's "include" (it now honors "exclude" too), so test
      // files — excluded there to keep them out of `tsc --noEmit` — don't get
      // "~/*" resolved. Set it explicitly so it applies everywhere, tests
      // included.
      alias: {
        '~': fileURLToPath(new URL('./src', import.meta.url))
      }
    },
    plugins: [tanstackStart(), viteReact()],
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test-setup.ts']
    }
  };
});

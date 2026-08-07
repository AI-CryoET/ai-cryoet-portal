import { SSR_DEFAULT_BASE } from '~/config/api';

function getBaseUrl(): string {
  if (import.meta.env.SSR) {
    return process.env.CRYOET_API_BASE_URL ?? SSR_DEFAULT_BASE;
  }
  return '/api';
}

export async function apiFetch<T = unknown>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const base = getBaseUrl();
  const url = `${base}${path.startsWith('/') ? path : `/${path}`}`;
  const res = await fetch(url, init);
  if (!res.ok) {
    throw new Error(`${init?.method ?? 'GET'} ${url} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/**
 * @fileglancer/client — browser client for the Fileglancer programmatic API.
 *
 * Fileglancer authenticates with a SameSite=Lax session cookie. Because the
 * integrating app and Fileglancer live under the same registrable domain
 * (e.g. *.janelia.org), the browser attaches that cookie to cross-subdomain
 * requests automatically — so every call here uses `credentials: 'include'`
 * and no tokens are handled by the app.
 *
 * When there is no session yet, `connect()` opens a short-lived popup to
 * Fileglancer's login flow and resolves once the user is authenticated. Call it
 * from a user gesture (e.g. a "Save" click) so the popup is not blocked.
 */

const CONNECT_MESSAGE_TYPE = 'fileglancer:connected';
const DEFAULT_POPUP_FEATURES = 'width=520,height=640,menubar=no,toolbar=no';

export interface FileglancerClientOptions {
  /** Base URL of the Fileglancer server, e.g. "https://fileglancer.int.janelia.org". */
  baseUrl: string;
  /**
   * On a 401, attempt a silent (hidden-iframe) re-connect and retry the request
   * once before failing. Defaults to true. A silent reconnect succeeds only if
   * the user still has a valid session; otherwise the call rejects with
   * AuthRequiredError and the app should call connect() from a user gesture.
   */
  autoConnect?: boolean;
  /** Window features string for the login popup. */
  popupFeatures?: string;
}

export interface AuthStatus {
  authenticated: boolean;
  username?: string;
  email?: string;
  auth_method?: 'simple' | 'okta';
}

export interface FileSharePath {
  name: string;
  zone?: string;
  group?: string;
  storage?: string;
  mount_path?: string;
  linux_path?: string;
  mac_path?: string;
  windows_path?: string;
}

export interface FileInfo {
  name: string;
  path: string;
  size: number;
  is_dir: boolean;
  last_modified?: number;
  permissions?: string;
  owner?: string;
  group?: string;
}

export interface ConnectOptions {
  /** Milliseconds to wait for the user to complete login before rejecting. */
  timeoutMs?: number;
}

/** Base error for all Fileglancer API failures. */
export class FileglancerError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'FileglancerError';
    this.status = status;
  }
}

/** Thrown when the request needs an authenticated session that isn't present. */
export class AuthRequiredError extends FileglancerError {
  constructor(message = 'Authentication required') {
    super(message, 401);
    this.name = 'AuthRequiredError';
  }
}

/** Thrown when this app's origin is not on the server's allowlist, or access is denied. */
export class ForbiddenError extends FileglancerError {
  constructor(message = 'Forbidden') {
    super(message, 403);
    this.name = 'ForbiddenError';
  }
}

/** Thrown when an If-Match / If-Unmodified-Since precondition fails (file changed). */
export class ConflictError extends FileglancerError {
  constructor(message = 'Precondition failed') {
    super(message, 412);
    this.name = 'ConflictError';
  }
}

export type WriteData = Blob | ArrayBuffer | ArrayBufferView | string;

export class FileglancerClient {
  private readonly baseUrl: string;
  private readonly baseOrigin: string;
  private readonly autoConnect: boolean;
  private readonly popupFeatures: string;

  constructor(options: FileglancerClientOptions) {
    if (!options?.baseUrl) {
      throw new Error('FileglancerClient requires a baseUrl');
    }
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.baseOrigin = new URL(this.baseUrl).origin;
    this.autoConnect = options.autoConnect ?? true;
    this.popupFeatures = options.popupFeatures ?? DEFAULT_POPUP_FEATURES;
  }

  // --- Authentication --------------------------------------------------------

  /** Return the current authentication status (works cross-origin, unauthenticated-safe). */
  async getAuthStatus(): Promise<AuthStatus> {
    const res = await fetch(`${this.baseUrl}/api/auth/status`, {
      credentials: 'include'
    });
    if (!res.ok) {
      throw await this.toError(res);
    }
    return (await res.json()) as AuthStatus;
  }

  /** Return the origins the server permits to use the API. */
  async getAllowedOrigins(): Promise<string[]> {
    const res = await fetch(`${this.baseUrl}/api/auth/allowed-origins`, {
      credentials: 'include'
    });
    if (!res.ok) {
      throw await this.toError(res);
    }
    const body = (await res.json()) as { origins: string[] };
    return body.origins ?? [];
  }

  /**
   * Try to confirm/establish the session without any visible UI, using a hidden
   * iframe. Resolves true if the user is authenticated, false otherwise. Safe to
   * call at app startup (no user gesture required); never opens a popup.
   */
  connectSilently(timeoutMs = 8000): Promise<boolean> {
    return new Promise<boolean>(resolve => {
      const iframe = document.createElement('iframe');
      iframe.style.display = 'none';
      iframe.setAttribute('aria-hidden', 'true');
      iframe.src = this.connectUrl(true);

      const done = this.waitForConnect(() => null, timeoutMs);
      document.body.appendChild(iframe);
      done.then(ok => {
        iframe.remove();
        resolve(ok);
      });
    });
  }

  /**
   * Ensure there is an authenticated session, opening a login popup if needed.
   * MUST be called from a user gesture (click/keydown) or the popup may be
   * blocked. Resolves with the auth status once connected; rejects on timeout,
   * a blocked popup, or if the user closes the popup without logging in.
   */
  async connect(options: ConnectOptions = {}): Promise<AuthStatus> {
    const timeoutMs = options.timeoutMs ?? 120000;

    // Reserve the popup synchronously to keep the user gesture, then try a
    // silent check first so an already-logged-in user sees only a brief flash
    // (or none, if the silent check wins before the popup paints).
    const popup = window.open('', 'fileglancer-connect', this.popupFeatures);
    try {
      if (await this.connectSilently()) {
        popup?.close();
        return await this.getAuthStatus();
      }
      if (!popup) {
        throw new AuthRequiredError(
          'Login popup was blocked. Call connect() directly from a click handler.'
        );
      }
      popup.location.href = this.connectUrl(false);
      const ok = await this.waitForConnect(() => popup, timeoutMs);
      if (!ok) {
        throw new AuthRequiredError('Login was not completed.');
      }
      return await this.getAuthStatus();
    } finally {
      if (popup && !popup.closed) {
        popup.close();
      }
    }
  }

  // --- File operations -------------------------------------------------------

  /** List all file share paths available to the user. */
  async getFileSharePaths(): Promise<FileSharePath[]> {
    const res = await this.request('/api/file-share-paths', { method: 'GET' });
    await this.assertOk(res);
    const body = (await res.json()) as { paths?: FileSharePath[] };
    return body.paths ?? [];
  }

  /**
   * List the contents of a directory, or return info for a single file/dir.
   * Returns the raw JSON payload from the server.
   */
  async listFiles(fsp: string, subpath = ''): Promise<unknown> {
    const res = await this.request(this.filesUrl('/api/files/', fsp, subpath), {
      method: 'GET'
    });
    await this.assertOk(res);
    return res.json();
  }

  /**
   * Read a file's contents. Returns the raw Response so callers can choose how
   * to consume it (`.blob()`, `.text()`, `.arrayBuffer()`, or stream `.body`).
   */
  async readFile(fsp: string, subpath: string): Promise<Response> {
    const res = await this.request(
      this.filesUrl('/api/content/', fsp, subpath),
      { method: 'GET' }
    );
    await this.assertOk(res);
    return res;
  }

  /** Read a file's contents as a Blob. */
  async readFileBlob(fsp: string, subpath: string): Promise<Blob> {
    return (await this.readFile(fsp, subpath)).blob();
  }

  /** Read a file's contents as text. */
  async readFileText(fsp: string, subpath: string): Promise<string> {
    return (await this.readFile(fsp, subpath)).text();
  }

  /**
   * Write (create or overwrite) a file's contents as the authenticated user.
   * The parent directory must already exist — use createDirectory() first.
   *
   * Optimistic concurrency: pass `ifMatch` (an ETag from a prior read's
   * `response.headers.get('etag')`) or `ifUnmodifiedSince` (a Last-Modified
   * value) to fail with a 412 ConflictError if the file changed since. Use
   * `'*'` for ifMatch to require the file already exist.
   */
  async writeFile(
    fsp: string,
    subpath: string,
    data: WriteData,
    options: { ifMatch?: string; ifUnmodifiedSince?: string } = {}
  ): Promise<{ bytes_written: number }> {
    const headers: Record<string, string> = {};
    if (options.ifMatch) {
      headers['If-Match'] = options.ifMatch;
    }
    if (options.ifUnmodifiedSince) {
      headers['If-Unmodified-Since'] = options.ifUnmodifiedSince;
    }
    const res = await this.request(
      this.filesUrl('/api/content/', fsp, subpath),
      { method: 'PUT', body: data as BodyInit, headers }
    );
    await this.assertOk(res);
    return (await res.json()) as { bytes_written: number };
  }

  /** Create a directory (parents must exist). */
  async createDirectory(fsp: string, subpath: string): Promise<void> {
    const res = await this.request(this.filesUrl('/api/files/', fsp, subpath), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'directory' })
    });
    await this.assertOk(res);
  }

  /** Create an empty file. */
  async createFile(fsp: string, subpath: string): Promise<void> {
    const res = await this.request(this.filesUrl('/api/files/', fsp, subpath), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'file' })
    });
    await this.assertOk(res);
  }

  /** Rename/move a file or directory within the same file share. */
  async rename(fsp: string, subpath: string, newPath: string): Promise<void> {
    const res = await this.request(this.filesUrl('/api/files/', fsp, subpath), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: newPath })
    });
    await this.assertOk(res);
  }

  /** Delete a file or (empty) directory. */
  async remove(fsp: string, subpath: string): Promise<void> {
    const res = await this.request(this.filesUrl('/api/files/', fsp, subpath), {
      method: 'DELETE'
    });
    await this.assertOk(res);
  }

  // --- Internals -------------------------------------------------------------

  private connectUrl(silent: boolean): string {
    const url = new URL('/connect-complete', this.baseUrl);
    url.searchParams.set('origin', window.location.origin);
    if (silent) {
      url.searchParams.set('silent', '1');
    }
    return url.toString();
  }

  private filesUrl(base: string, fsp: string, subpath: string): string {
    const url = new URL(base + encodeURIComponent(fsp), this.baseUrl);
    if (subpath) {
      url.searchParams.set('subpath', subpath);
    }
    // Return path+query relative to baseUrl for request() to resolve.
    return url.pathname + url.search;
  }

  private async request(
    path: string,
    init: RequestInit,
    retry = true
  ): Promise<Response> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      credentials: 'include'
    });
    if (res.status === 401 && retry && this.autoConnect) {
      // Session may have lapsed; try to restore it silently, then retry once.
      const ok = await this.connectSilently();
      if (ok) {
        return this.request(path, init, false);
      }
    }
    return res;
  }

  /**
   * Wait for a `fileglancer:connected` postMessage from the Fileglancer origin.
   * `getWindow` returns the popup to watch for premature closure, or null (for
   * the hidden-iframe case where there is nothing to poll).
   */
  private waitForConnect(
    getWindow: () => Window | null,
    timeoutMs: number
  ): Promise<boolean> {
    return new Promise<boolean>(resolve => {
      let settled = false;
      let poll: ReturnType<typeof setInterval> | undefined;
      let timer: ReturnType<typeof setTimeout> | undefined;

      const cleanup = () => {
        window.removeEventListener('message', onMessage);
        if (poll !== undefined) {
          clearInterval(poll);
        }
        if (timer !== undefined) {
          clearTimeout(timer);
        }
      };
      const finish = (value: boolean) => {
        if (settled) {
          return;
        }
        settled = true;
        cleanup();
        resolve(value);
      };
      const onMessage = (event: MessageEvent) => {
        if (event.origin !== this.baseOrigin) {
          return;
        }
        const data = event.data as { type?: string; authenticated?: boolean };
        if (!data || data.type !== CONNECT_MESSAGE_TYPE) {
          return;
        }
        finish(Boolean(data.authenticated));
      };

      window.addEventListener('message', onMessage);
      timer = setTimeout(() => finish(false), timeoutMs);

      const watched = getWindow();
      if (watched) {
        poll = setInterval(() => {
          if (watched.closed) {
            finish(false);
          }
        }, 400);
      }
    });
  }

  private async assertOk(res: Response): Promise<void> {
    if (!res.ok) {
      throw await this.toError(res);
    }
  }

  private async toError(res: Response): Promise<FileglancerError> {
    let detail = res.statusText;
    try {
      const body = await res.clone().json();
      detail = body?.error ?? body?.detail ?? detail;
    } catch {
      // non-JSON body; keep statusText
    }
    if (res.status === 401) {
      return new AuthRequiredError(detail || 'Authentication required');
    }
    if (res.status === 403) {
      return new ForbiddenError(detail || 'Forbidden');
    }
    if (res.status === 412) {
      return new ConflictError(detail || 'Precondition failed');
    }
    return new FileglancerError(
      detail || `Request failed (${res.status})`,
      res.status
    );
  }
}

export default FileglancerClient;

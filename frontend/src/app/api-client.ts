import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";

/**
 * The access token lives only in this module-scoped variable — never
 * localStorage/sessionStorage (Spec 14.2). `auth-context.tsx` is the only
 * writer, via `setAccessToken`, so a page reload always starts from `null`
 * and the app has to prove itself via `POST /auth/refresh` again.
 */
let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

/** Set once by AuthProvider. Called when a refresh-and-retry both fail —
 * the interceptor's only way to say "the session is really over" without
 * importing the auth context and creating a cycle. */
let onSessionExpired: (() => void) | null = null;

export function setOnSessionExpired(handler: () => void): void {
  onSessionExpired = handler;
}

export const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000/api/v1";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  // The refresh token is an httpOnly cookie (Spec 9.2) — the browser only
  // attaches/accepts it cross-origin when the request carries credentials.
  withCredentials: true,
});

apiClient.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

// A bare instance for the refresh call itself — it must never go through
// the response interceptor below, or a failed refresh would trigger
// another refresh attempt and loop forever (Spec 14.2's explicit warning).
const refreshClient = axios.create({ baseURL: API_BASE_URL, withCredentials: true });

// Single-flight guard (hardening pass): the refresh token ROTATES on every
// use (Spec 9.2) and a reused, already-rotated token trips reuse detection,
// which revokes the whole session family — by design, that's how theft
// gets caught. But react-query fires several queries in parallel (e.g. a
// dashboard loading three widgets at once), and if the access token expires
// mid-page every one of those requests gets its own 401 at nearly the same
// moment. Without this guard, each 401 called refreshAccessToken()
// independently; the first refresh call rotates the cookie, and every
// concurrent call after it presents the now-already-rotated token — which
// looks exactly like theft to the backend and force-logs-out a user who did
// nothing wrong. One in-flight refresh is shared by every caller instead.
let refreshPromise: Promise<string> | null = null;

async function refreshAccessToken(): Promise<string> {
  if (!refreshPromise) {
    refreshPromise = refreshClient
      .post<{ access_token: string }>("/auth/refresh")
      .then(({ data }) => data.access_token)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

interface RetryableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean;
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetryableConfig | undefined;
    const isAuthRoute = config?.url?.startsWith("/auth/login") || config?.url?.startsWith("/auth/refresh");

    if (error.response?.status !== 401 || !config || config._retried || isAuthRoute) {
      throw error;
    }

    config._retried = true;
    try {
      const newToken = await refreshAccessToken();
      setAccessToken(newToken);
      config.headers.Authorization = `Bearer ${newToken}`;
      return apiClient(config);
    } catch (refreshError) {
      setAccessToken(null);
      onSessionExpired?.();
      throw refreshError;
    }
  },
);

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

async function refreshAccessToken(): Promise<string> {
  const { data } = await refreshClient.post<{ access_token: string }>("/auth/refresh");
  return data.access_token;
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

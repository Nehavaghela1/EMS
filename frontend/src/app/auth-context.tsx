import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiClient, setAccessToken, setOnSessionExpired } from "./api-client";

export type UserRole = "employee" | "manager" | "hr_admin" | "super_admin";

export interface EmployeeSummary {
  id: string;
  employee_code: string;
  first_name: string;
  last_name: string | null;
  department_id: string | null;
  position: string | null;
}

export interface CurrentUser {
  id: string;
  email: string;
  role: UserRole;
  company_id: string;
  is_active: boolean;
  must_change_password: boolean;
  employee: EmployeeSummary | null;
  permissions: string[];
}

interface TokenResponse {
  access_token: string;
  token_type: string;
}

type AuthStatus = "loading" | "authenticated" | "unauthenticated";

interface AuthContextValue {
  status: AuthStatus;
  user: CurrentUser | null;
  login: (email: string, password: string, companyCode?: string) => Promise<void>;
  /** `POST /auth/activate` (route 11) already logs the caller in and
   * returns the same token shape login() does (Spec 10.2) — this adopts
   * an access token already obtained elsewhere instead of calling
   * `/auth/login` a second time. */
  establishSession: (accessToken: string) => Promise<void>;
  logout: () => Promise<void>;
  /** True only when the API interceptor's refresh-and-retry both failed on
   * an already-in-flight request (a session that was good, then wasn't) —
   * never on the ordinary "never logged in yet" boot check. LoginPage reads
   * this to explain the redirect instead of showing a blank form with no
   * indication anything happened. */
  sessionExpired: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

async function fetchMe(): Promise<CurrentUser> {
  const { data } = await apiClient.get<CurrentUser>("/auth/me");
  return data;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);

  const clearSession = useCallback(() => {
    setAccessToken(null);
    setUser(null);
    setStatus("unauthenticated");
  }, []);

  // The interceptor calls this when a refresh-and-retry both fail — the
  // session is over from an already-in-flight request, not just at boot,
  // which is the one case worth telling the user about on the way back to
  // the login page.
  useEffect(() => {
    setOnSessionExpired(() => {
      setSessionExpired(true);
      clearSession();
    });
  }, [clearSession]);

  useEffect(() => {
    // Spec 14.2: one refresh call on app load. Success means the httpOnly
    // cookie is still good; failure just means "show the login page," not
    // an error to surface anywhere.
    let cancelled = false;
    async function bootstrap() {
      try {
        const { data } = await apiClient.post<TokenResponse>("/auth/refresh");
        if (cancelled) return;
        setAccessToken(data.access_token);
        const me = await fetchMe();
        if (cancelled) return;
        setUser(me);
        setStatus("authenticated");
      } catch {
        if (cancelled) return;
        clearSession();
      }
    }
    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [clearSession]);

  const establishSession = useCallback(async (accessToken: string) => {
    setAccessToken(accessToken);
    const me = await fetchMe();
    setUser(me);
    setStatus("authenticated");
    setSessionExpired(false);
  }, []);

  const login = useCallback(
    async (email: string, password: string, companyCode?: string) => {
      const { data } = await apiClient.post<TokenResponse>("/auth/login", {
        email,
        password,
        company_code: companyCode || undefined,
      });
      await establishSession(data.access_token);
    },
    [establishSession],
  );

  const logout = useCallback(async () => {
    try {
      await apiClient.post("/auth/logout");
    } finally {
      clearSession();
    }
  }, [clearSession]);

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, login, establishSession, logout, sessionExpired }),
    [status, user, login, establishSession, logout, sessionExpired],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

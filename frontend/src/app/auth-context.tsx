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
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

async function fetchMe(): Promise<CurrentUser> {
  const { data } = await apiClient.get<CurrentUser>("/auth/me");
  return data;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<CurrentUser | null>(null);

  const clearSession = useCallback(() => {
    setAccessToken(null);
    setUser(null);
    setStatus("unauthenticated");
  }, []);

  // The interceptor calls this when a refresh-and-retry both fail — the
  // session is over from an already-in-flight request, not just at boot.
  useEffect(() => {
    setOnSessionExpired(clearSession);
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

  const login = useCallback(async (email: string, password: string, companyCode?: string) => {
    const { data } = await apiClient.post<TokenResponse>("/auth/login", {
      email,
      password,
      company_code: companyCode || undefined,
    });
    setAccessToken(data.access_token);
    const me = await fetchMe();
    setUser(me);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiClient.post("/auth/logout");
    } finally {
      clearSession();
    }
  }, [clearSession]);

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, login, logout }),
    [status, user, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

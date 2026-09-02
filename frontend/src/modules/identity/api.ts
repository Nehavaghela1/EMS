import { apiClient } from "../../app/api-client";
import type { Page } from "../../shared/api/pagination";

/** Mirrors app/modules/identity/schemas.py::CompanyRegisterRequest exactly
 * (field names read from the generated shared/api/types.gen.ts, not
 * guessed) — `country` is omitted when unset so the backend's own
 * `= "IN"` default applies. */
export interface RegisterCompanyInput {
  company_name: string;
  company_email: string;
  industry?: string;
  phone?: string;
}

export interface CompanyResponse {
  id: string;
  name: string;
  code: string;
  email: string;
  industry: string | null;
  country: string;
  status: string;
  created_at: string;
}

export async function registerCompany(input: RegisterCompanyInput): Promise<CompanyResponse> {
  const { data } = await apiClient.post<CompanyResponse>("/companies/register", input);
  return data;
}

/** GET /industry-presets (WP-14, no route number assigned in Section 10 —
 * see RECONCILIATION.md). Public, names only. */
export async function listIndustryPresets(): Promise<string[]> {
  const { data } = await apiClient.get<string[]>("/industry-presets");
  return data;
}

export interface ActivationPreview {
  first_name: string;
  last_name: string | null;
  company_name: string;
  expires_at: string;
}

export async function previewActivation(token: string): Promise<ActivationPreview> {
  const { data } = await apiClient.get<ActivationPreview>(`/auth/activate/${encodeURIComponent(token)}`);
  return data;
}

export interface ActivateAccountInput {
  token: string;
  username: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export async function activateAccount(input: ActivateAccountInput): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>("/auth/activate", input);
  return data;
}

export async function forgotPassword(email: string): Promise<{ message: string }> {
  const { data } = await apiClient.post<{ message: string }>("/auth/forgot-password", { email });
  return data;
}

export interface ResetPasswordInput {
  email: string;
  otp: string;
  new_password: string;
}

export async function resetPassword(input: ResetPasswordInput): Promise<void> {
  await apiClient.post("/auth/reset-password", input);
}

// --- Companies (page 5, super_admin) --------------------------------------

export async function listPendingCompanies(page: number, limit: number): Promise<Page<CompanyResponse>> {
  const { data } = await apiClient.get<Page<CompanyResponse>>("/companies", {
    params: { status: "pending", page, limit },
  });
  return data;
}

export interface CompanyApproveResult {
  company: CompanyResponse;
  hr_admin_email: string;
  temporary_password: string;
}

export async function approveCompany(id: string): Promise<CompanyApproveResult> {
  const { data } = await apiClient.post<CompanyApproveResult>(`/companies/${id}/approve`);
  return data;
}

export async function rejectCompany(id: string, reason: string): Promise<CompanyResponse> {
  const { data } = await apiClient.post<CompanyResponse>(`/companies/${id}/reject`, { reason });
  return data;
}

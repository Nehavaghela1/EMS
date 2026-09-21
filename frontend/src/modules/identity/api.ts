import { apiClient } from "../../app/api-client";
import type { Page } from "../../shared/api/pagination";

/** Mirrors app/modules/identity/schemas.py::CompanyRegisterRequest exactly
 * (field names read from the generated shared/api/types.gen.ts, not
 * guessed) — `country` is omitted when unset so the backend's own
 * `= "IN"` default applies. */
export interface RegisterCompanyInput {
  company_name: string;
  company_email: string;
  subdomain?: string;
  company_size?: string;
  password?: string;
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
  subdomain?: string | null;
  company_size?: string | null;
  phone?: string | null;
  address?: string | null;
  city?: string | null;
  state?: string | null;
  pincode?: string | null;
  website?: string | null;
  logo_url?: string | null;
  gst_number?: string | null;
  pan_number?: string | null;
  created_at: string;
}

export async function getMyCompany(): Promise<CompanyResponse> {
  const { data } = await apiClient.get<CompanyResponse>("/companies/me");
  return data;
}

export async function registerCompany(input: RegisterCompanyInput): Promise<CompanyResponse> {
  const { data } = await apiClient.post<CompanyResponse>("/companies/register", input);
  return data;
}

export interface CreateWorkspaceInput {
  company_name: string;
  company_email?: string;
  subdomain?: string;
  country?: string;
  currency?: string;
  timezone?: string;
  seed_departments?: boolean;
  seed_shift?: boolean;
}

export interface UserWorkspaceResponse {
  id: string;
  name: string;
  code: string;
  role: string;
  is_active: boolean;
}

export interface CreateWorkspaceResponse {
  company: CompanyResponse;
  access_token: string;
  token_type: string;
}

export async function createWorkspace(input: CreateWorkspaceInput): Promise<CreateWorkspaceResponse> {
  const { data } = await apiClient.post<CreateWorkspaceResponse>("/companies/workspaces", input);
  return data;
}

export async function getUserWorkspaces(): Promise<UserWorkspaceResponse[]> {
  const { data } = await apiClient.get<UserWorkspaceResponse[]>("/auth/workspaces");
  return data;
}

export async function switchWorkspace(companyId: string): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>("/auth/switch-workspace", { company_id: companyId });
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

export interface CompanyDetailResponse extends CompanyResponse {
  phone: string | null;
  rejection_reason: string | null;
  approved_at: string | null;
  counts: Record<string, number>;
}

export interface AdminCompanyUpdateInput {
  name?: string;
  phone?: string;
  industry?: string;
  address?: string;
  city?: string;
  state?: string;
  pincode?: string;
  website?: string;
  status?: string;
}

export async function listCompanies(params?: {
  status?: string;
  q?: string;
  page?: number;
  limit?: number;
  sort?: string;
}): Promise<Page<CompanyResponse>> {
  const { data } = await apiClient.get<Page<CompanyResponse>>("/companies", {
    params: {
      status: params?.status && params.status !== "all" ? params.status : undefined,
      q: params?.q || undefined,
      page: params?.page ?? 1,
      limit: params?.limit ?? 15,
      sort: params?.sort || undefined,
    },
  });
  return data;
}

export async function getCompanyDetail(id: string): Promise<CompanyDetailResponse> {
  const { data } = await apiClient.get<CompanyDetailResponse>(`/companies/${id}`);
  return data;
}

export async function updateCompanyByAdmin(
  id: string,
  input: AdminCompanyUpdateInput
): Promise<CompanyResponse> {
  const { data } = await apiClient.put<CompanyResponse>(`/companies/${id}`, input);
  return data;
}

export async function listPendingCompanies(page: number, limit: number): Promise<Page<CompanyResponse>> {
  const { data } = await apiClient.get<Page<CompanyResponse>>("/companies", {
    params: { status: "pending", page, limit },
  });
  return data;
}

export interface CompanyApproveResult {
  company: CompanyResponse;
  hr_admin_email: string;
}

export async function approveCompany(id: string): Promise<CompanyApproveResult> {
  const { data } = await apiClient.post<CompanyApproveResult>(`/companies/${id}/approve`);
  return data;
}

export async function rejectCompany(id: string, reason: string): Promise<CompanyResponse> {
  const { data } = await apiClient.post<CompanyResponse>(`/companies/${id}/reject`, { reason });
  return data;
}

// --- Settings page (page 27) -----------------------------------------------

export interface ChangePasswordInput {
  current_password: string;
  new_password: string;
}

/** Route 6 — revokes every other signed-in session (Spec 9's own rule).
 * The settings page must tell the user that before they submit. */
export async function changePassword(input: ChangePasswordInput): Promise<void> {
  await apiClient.post("/auth/change-password", input);
}

// --- Locations ---

export interface CompanyLocation {
  id: string;
  company_id: string;
  name: string;
  code: string;
  address_line1?: string;
  city?: string;
  state?: string;
  country: string;
  postal_code?: string;
  is_primary: boolean;
  latitude?: number | null;
  longitude?: number | null;
  geofence_radius_meters?: number | null;
  is_remote_exempt?: boolean;
  created_at: string;
  updated_at: string;
}

export interface CompanyLocationCreate {
  name: string;
  code: string;
  address_line1?: string;
  city?: string;
  state?: string;
  country?: string;
  postal_code?: string;
  is_primary?: boolean;
  latitude?: number | null;
  longitude?: number | null;
  geofence_radius_meters?: number | null;
  is_remote_exempt?: boolean;
}

export async function listLocations(): Promise<CompanyLocation[]> {
  const { data } = await apiClient.get<CompanyLocation[]>("/companies/locations");
  return data;
}

export async function createLocation(input: CompanyLocationCreate): Promise<CompanyLocation> {
  const { data } = await apiClient.post<CompanyLocation>("/companies/locations", input);
  return data;
}

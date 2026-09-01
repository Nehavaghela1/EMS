import { apiClient } from "../../app/api-client";

export interface DashboardResponse {
  role: string;
  generated_at: string;
  data: Record<string, unknown>;
}

export async function fetchDashboard(): Promise<DashboardResponse> {
  const { data } = await apiClient.get<DashboardResponse>("/dashboard");
  return data;
}

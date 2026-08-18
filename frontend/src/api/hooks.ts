import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, setToken } from "./client";
import type { Dashboard, Organization, Page, TokenResponse } from "./types";

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (creds: { email: string; password: string }) =>
      api.post<TokenResponse>("/auth/login", creds),
    onSuccess: (data) => {
      setToken(data.access_token);
      qc.invalidateQueries();
      // Minimal SPA: no router; reload so <App> re-evaluates auth and shows the dashboard.
      window.location.reload();
    },
  });
}

export function useOrganizations() {
  return useQuery({
    queryKey: ["organizations"],
    queryFn: () => api.get<Page<Organization>>("/organizations"),
  });
}

export function useDashboard(orgId: string | null, days = 7) {
  return useQuery({
    enabled: !!orgId,
    queryKey: ["dashboard", orgId, days],
    queryFn: () => api.get<Dashboard>(`/organizations/${orgId}/dashboard?days=${days}`),
    refetchInterval: 15_000,
  });
}

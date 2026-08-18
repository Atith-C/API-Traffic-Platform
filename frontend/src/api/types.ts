export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  refresh_token: string;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  created_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface DashboardSummary {
  request_count: number;
  error_count: number;
  error_rate: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  active_keys: number;
  window_days: number;
}

export interface EndpointStat {
  path: string;
  request_count: number;
  avg_latency_ms: number;
}

export interface Dashboard {
  summary: DashboardSummary;
  top_endpoints: EndpointStat[];
  status_breakdown: Record<string, number>;
  top_keys: { api_key_id: string; request_count: number; error_count: number }[];
  api_count: number;
}

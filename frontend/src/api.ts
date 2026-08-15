// API client — token in localStorage, JSON helpers. Base URL: same origin
// when served by the backend; VITE_API_URL (default :8000) for `npm run dev`.

const BASE: string =
  (import.meta.env.VITE_API_URL as string | undefined) ??
  (window.location.port === "5173" ? "http://localhost:8000" : "");

export function getToken(): string | null {
  return localStorage.getItem("crs_token");
}
export function getRole(): string | null {
  return localStorage.getItem("crs_role");
}
export function getUsername(): string | null {
  return localStorage.getItem("crs_username");
}
export function clearSession(): void {
  localStorage.removeItem("crs_token");
  localStorage.removeItem("crs_role");
  localStorage.removeItem("crs_username");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (init.body && !(init.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`${BASE}${path}`, { ...init, headers });
  if (response.status === 401 && path !== "/auth/login") {
    clearSession();
    window.location.hash = "#/login";
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export async function login(username: string, password: string): Promise<void> {
  const data = await request<{ token: string; username: string; role: string }>(
    "/auth/login",
    { method: "POST", body: JSON.stringify({ username, password }) },
  );
  localStorage.setItem("crs_token", data.token);
  localStorage.setItem("crs_role", data.role);
  localStorage.setItem("crs_username", data.username);
}

export interface UploadResult {
  filename: string;
  document_id: string;
  duplicate: boolean;
  sha256: string;
}

export function uploadFiles(files: FileList): Promise<{ results: UploadResult[] }> {
  const form = new FormData();
  Array.from(files).forEach((f) => form.append("files", f));
  return request("/ingest/upload", { method: "POST", body: form });
}

export interface QueueItem {
  document_id: string;
  filename: string;
  status: string;
  uploaded_by: string;
  created_at: string;
  family: string | null;
  suggested_decision: string | null;
  finding_count: number | null;
  high_severity: number | null;
}

export const getQueue = () => request<QueueItem[]>("/review/queue");

export interface Finding {
  citation: string;
  severity: string;
  title: string;
  description: string;
}

export type ClauseStatus =
  | "standard" | "borderline" | "deviation" | "missing" | "extra";

export interface TemplateClause {
  heading: string;
  template_text: string;
  status: ClauseStatus;
  similarity: number | null;
  section_id: string | null;
  doc_heading: string | null;
  sent_to_llm: boolean;
}

export interface ReferenceTemplate {
  family: string;
  title: string;
  family_score: number;
  thresholds: { standard: number; deviation: number };
  clauses: TemplateClause[];
}

export interface ContractDetail {
  document: {
    id: string;
    filename: string;
    status: string;
    uploaded_by: string;
    created_at: string;
  };
  masked_text: string | null;
  sections: { section_id: string; heading: string; start: number; end: number }[];
  chunks: { chunk_id: string; section_id: string; heading: string; start: number; end: number }[];
  reference_template: ReferenceTemplate | null;
  analysis: {
    family: string | null;
    findings: Finding[];
    key_terms: Record<string, unknown> | null;
    suggested_decision: string;
    rationale: string;
    models: { strong: string; fast: string };
    latency_ms: number;
  } | null;
  decisions: { action: string; rationale: string; reviewer: string; created_at: string }[];
}

export const getContract = (id: string) => request<ContractDetail>(`/review/contracts/${id}`);
export const claimContract = (id: string) =>
  request(`/review/contracts/${id}/claim`, { method: "POST" });
export const decideContract = (id: string, action: string, rationale: string) =>
  request(`/review/contracts/${id}/decision`, {
    method: "POST",
    body: JSON.stringify({ action, rationale }),
  });

export interface AuditEvent {
  actor_type: string;
  actor_id: string;
  action: string;
  detail: Record<string, unknown> | null;
  rationale: string | null;
  created_at: string;
}
export const getAudit = (id: string) => request<AuditEvent[]>(`/review/contracts/${id}/audit`);

export interface Metrics {
  documents_by_status: Record<string, number>;
  total_documents: number;
  open_pii_holds: number;
  avg_analysis_latency_ms: number | null;
  decisions_by_action: Record<string, number>;
}
export const getMetrics = () => request<Metrics>("/review/metrics");

export interface PiiHold {
  id: number;
  document_id: string;
  flag_type: string;
  span_text: string;
  detector: string;
  score: number | null;
  status: string;
  created_at: string;
}
export const getHolds = () => request<PiiHold[]>("/pii/holds");
export const resolveHold = (
  id: number,
  action: "add_to_master" | "dismiss",
  extra: { entity_type?: string; rationale?: string },
) => request(`/pii/holds/${id}/resolve`, { method: "POST", body: JSON.stringify({ action, ...extra }) });

export interface MasterEntity {
  id: string;
  value: string;
  entity_type: string;
  created_by: string;
}
export const getMaster = () => request<MasterEntity[]>("/pii/master");
export const addMaster = (value: string, entity_type: string) =>
  request("/pii/master", { method: "POST", body: JSON.stringify({ value, entity_type }) });

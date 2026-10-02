import type { ApiEnvelope, CreateTextEvidenceRequest, Evidence, EvidenceHistoricalSearchResult, HistoricalCaseDetail, HistoricalImageSearchResult, HistoricalIndexStatus, Investigation, UpdateEvidenceRequest, ResearchRun, ResearchSearchType, ResearchSource, AgentRun, AgentAction, CorrelationRecord, CorrelationSummary, CorrelationRunResult, CorrelationReviewStatus, TimelineEvent, GeoLocation, GeoSummary, Contradiction } from "./types";

const baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    const headers = new Headers(init?.headers);
    if (!(init?.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    response = await fetch(`${baseUrl}${path}`, { ...init, headers, cache: "no-store" });
  } catch {
    throw new Error("Unable to connect to ColdSync backend. Please check that the API service is running.");
  }
  if (response.status === 204) return undefined as T;
  const envelope = await response.json() as ApiEnvelope<T>;
  if (!response.ok || !envelope.success) throw new Error(envelope.success ? "The request could not be completed." : envelope.error.message);
  return envelope.data;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete: (path: string) => request<void>(path, { method: "DELETE" }),
  investigations: () => request<Investigation[]>("/investigations"),
  investigation: (id: string) => request<Investigation>(`/investigations/${encodeURIComponent(id)}`),
  evidence: (investigationId: string, filters?: { type?: string; processing_status?: string }) => {
    const query = new URLSearchParams();
    if (filters?.type) query.set("type", filters.type);
    if (filters?.processing_status) query.set("processing_status", filters.processing_status);
    return request<Evidence[]>(`/investigations/${encodeURIComponent(investigationId)}/evidence${query.size ? `?${query}` : ""}`);
  },
  createTextEvidence: (investigationId: string, data: CreateTextEvidenceRequest) => request<Evidence>(`/investigations/${encodeURIComponent(investigationId)}/evidence`, { method: "POST", body: JSON.stringify(data) }),
  uploadEvidence: (investigationId: string, file: File, title: string, description: string) => {
    const form = new FormData(); form.append("file", file); form.append("title", title); form.append("description", description);
    return request<Evidence>(`/investigations/${encodeURIComponent(investigationId)}/evidence/upload`, { method: "POST", body: form });
  },
  updateEvidence: (id: string, data: UpdateEvidenceRequest) => request<Evidence>(`/evidence/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteEvidence: (id: string) => request<void>(`/evidence/${encodeURIComponent(id)}`, { method: "DELETE" }),
  evidenceContentUrl: (id: string) => `${baseUrl}/evidence/${encodeURIComponent(id)}/content`,
  searchInvestigationHistorical: (investigationId: string, evidence_ids: string[], top_k: number) => request<EvidenceHistoricalSearchResult>(`/investigations/${encodeURIComponent(investigationId)}/historical-search`, { method: "POST", body: JSON.stringify({ evidence_ids, top_k }) }),
  historicalCase: (id: string) => request<HistoricalCaseDetail>(`/historical/${encodeURIComponent(id)}`),
  historicalIndexStatus: () => request<HistoricalIndexStatus>("/historical/index-status"),
  searchInvestigationHistoricalImages: (investigationId: string, evidence_id: string, top_k: number) => request<HistoricalImageSearchResult>(`/investigations/${encodeURIComponent(investigationId)}/historical-image-search`, { method: "POST", body: JSON.stringify({ evidence_id, top_k }) }),
  historicalImageContentUrl: (id: string) => `${baseUrl}/historical/images/${encodeURIComponent(id)}/content`,
  researchManual: (investigationId: string, query: string, search_type: ResearchSearchType) => request<ResearchRun>(`/investigations/${encodeURIComponent(investigationId)}/research/search`, { method: "POST", body: JSON.stringify({ query, search_type }) }),
  researchFromEvidence: (investigationId: string, evidence_ids: string[]) => request<ResearchRun>(`/investigations/${encodeURIComponent(investigationId)}/research/from-evidence`, { method: "POST", body: JSON.stringify({ evidence_ids }) }),
  researchRuns: (investigationId: string, offset = 0) => request<{ items: ResearchRun[]; limit: number; offset: number }>(`/investigations/${encodeURIComponent(investigationId)}/research/runs?limit=25&offset=${offset}`),
  researchRun: (investigationId: string, runId: string) => request<ResearchRun>(`/investigations/${encodeURIComponent(investigationId)}/research/runs/${encodeURIComponent(runId)}`),
  researchSources: (investigationId: string, q = "", offset = 0) => request<{ items: ResearchSource[]; total: number; limit: number; offset: number }>(`/investigations/${encodeURIComponent(investigationId)}/sources?limit=25&offset=${offset}${q ? `&q=${encodeURIComponent(q)}` : ""}`),
  researchUsage: (investigationId: string) => request<{ search_count: number; today_search_count: number; result_count: number; successful_search_count: number; failed_search_count: number; configured: boolean; demo_mode: boolean; recent_status: string }>(`/investigations/${encodeURIComponent(investigationId)}/research/usage`),
  startAgent: (investigationId: string, objective: string, limits?: { max_iterations?: number; max_serpapi_queries?: number }) => request<AgentRun>(`/investigations/${encodeURIComponent(investigationId)}/agent/run`, { method: "POST", body: JSON.stringify({ objective, ...limits }) }),
  agentRuns: (investigationId: string) => request<{ items: AgentRun[]; limit: number; offset: number }>(`/investigations/${encodeURIComponent(investigationId)}/agent/runs`),
  agentRun: (runId: string) => request<AgentRun>(`/agent/runs/${encodeURIComponent(runId)}`),
  agentActions: (runId: string) => request<{ items: AgentAction[] }>(`/agent/runs/${encodeURIComponent(runId)}/actions`),
  stopAgent: (runId: string) => request<AgentRun>(`/agent/runs/${encodeURIComponent(runId)}/stop`, { method: "POST", body: JSON.stringify({}) }),
  correlations: (investigationId: string, filters: { correlation_type?: string; source_type?: string; target_type?: string; minimum_score?: number; review_status?: CorrelationReviewStatus; reviewed?: boolean; evidence_id?: string; matrix_group?: string } = {}, offset = 0) => {
    const query = new URLSearchParams(); for (const [key, value] of Object.entries(filters)) if (value !== undefined) query.set(key, String(value));
    query.set("limit", "500");
    query.set("offset", String(offset));
    return request<{ items: CorrelationRecord[]; total: number; limit: number; offset: number; summary: CorrelationSummary }>(`/investigations/${encodeURIComponent(investigationId)}/correlations?${query}`);
  },
  runCorrelations: (investigationId: string, scope = "ALL") => request<CorrelationRunResult>(`/investigations/${encodeURIComponent(investigationId)}/correlations/run`, { method: "POST", body: JSON.stringify({ scope }) }),
  correlation: (id: string) => request<CorrelationRecord>(`/correlations/${encodeURIComponent(id)}`),
  reviewCorrelation: (id: string, review_status: CorrelationReviewStatus, note?: string) => request<CorrelationRecord>(`/correlations/${encodeURIComponent(id)}/review`, { method: "PATCH", body: JSON.stringify({ review_status, note }) }),
  deleteCorrelation: (id: string) => request<void>(`/correlations/${encodeURIComponent(id)}`, { method: "DELETE"}),
  createManualCorrelation: (investigationId: string, data: { source_type: string; source_id: string; target_type: string; target_id: string; correlation_type: string; note: string }) => request<CorrelationRecord>(`/investigations/${encodeURIComponent(investigationId)}/correlations/manual`, { method: "POST", body: JSON.stringify(data) }),
  timeline: (investigationId:string, filters:Record<string,string>={}) => { const q=new URLSearchParams(filters); return request<TimelineEvent[]>(`/investigations/${encodeURIComponent(investigationId)}/timeline${q.size?`?${q}`:""}`); },
  generateTimeline: (investigationId:string,scope="ALL") => request<{status:string;scope:string;created:number;partial_sources:string[];events:TimelineEvent[]}>(`/investigations/${encodeURIComponent(investigationId)}/timeline/generate`,{method:"POST",body:JSON.stringify({scope})}),
  createTimelineEvent: (investigationId:string,data:Record<string,unknown>) => request<TimelineEvent>(`/investigations/${encodeURIComponent(investigationId)}/timeline/events`,{method:"POST",body:JSON.stringify(data)}),
  updateTimelineEvent: (id:string,data:Record<string,unknown>) => request<TimelineEvent>(`/timeline/events/${encodeURIComponent(id)}`,{method:"PATCH",body:JSON.stringify(data)}),
  deleteTimelineEvent: (id:string) => request<void>(`/timeline/events/${encodeURIComponent(id)}`,{method:"DELETE"}),
  timelineEvent: (id:string) => request<TimelineEvent>(`/timeline/events/${encodeURIComponent(id)}`),
  geospatialLocations:(investigationId:string,filters:Record<string,string>={})=>{const q=new URLSearchParams(filters);return request<GeoLocation[]>(`/investigations/${encodeURIComponent(investigationId)}/geospatial/locations${q.size?`?${q}`:""}`)},
  geospatialSummary:(investigationId:string)=>request<GeoSummary>(`/investigations/${encodeURIComponent(investigationId)}/geospatial/summary`),
  geospatialHeatmap:(investigationId:string,filters:Record<string,string>={})=>{const q=new URLSearchParams(filters);return request<{mode:string;methodology:string;record_count:number;points:Array<{location_id:string;latitude:number;longitude:number;precision:string;raw_text:string;weight:number;record:import("./types").GeoRecord;conflicts:Array<{id:string;type:string;status:string;description:string}>}>;correlations:Array<{id:string;coordinates:[[number,number],[number,number]];source_location:string;target_location:string;explanation:string;score:number|null}>}>(`/investigations/${encodeURIComponent(investigationId)}/geospatial/heatmap?${q}`)},
  rebuildGeospatial:(investigationId:string)=>request<unknown>(`/investigations/${encodeURIComponent(investigationId)}/geospatial/rebuild`,{method:"POST",body:JSON.stringify({})}),
  geocodeLocations:(investigationId:string,limit=25)=>request<unknown>(`/investigations/${encodeURIComponent(investigationId)}/geospatial/geocode`,{method:"POST",body:JSON.stringify({limit})}),
  createGeoLocation:(investigationId:string,data:Record<string,unknown>)=>request<GeoLocation>(`/investigations/${encodeURIComponent(investigationId)}/geospatial/locations`,{method:"POST",body:JSON.stringify(data)}),
  detectContradictions:(investigationId:string)=>request<{status:string;created:number;items:Contradiction[]}>(`/investigations/${encodeURIComponent(investigationId)}/contradictions/detect`,{method:"POST",body:JSON.stringify({})}),
  contradictions:(investigationId:string,filters:Record<string,string>={})=>{const q=new URLSearchParams(filters);return request<Contradiction[]>(`/investigations/${encodeURIComponent(investigationId)}/contradictions${q.size?`?${q}`:""}`)},
  contradiction:(id:string)=>request<Contradiction>(`/contradictions/${encodeURIComponent(id)}`),
  reviewContradiction:(id:string,status:string,note?:string)=>request<Contradiction>(`/contradictions/${encodeURIComponent(id)}`,{method:"PATCH",body:JSON.stringify({status,investigator_note:note})}),
  deleteContradiction:(id:string)=>request<void>(`/contradictions/${encodeURIComponent(id)}`,{method:"DELETE"}),
};

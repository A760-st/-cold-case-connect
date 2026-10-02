"use client";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { Check, Circle, Play, RefreshCw, Square, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import type { AgentAction, AgentRun } from "@/lib/types";

const labels: Record<string, string> = { GET_INVESTIGATION: "Loaded investigation", GET_EVIDENCE: "Reviewed evidence", GET_RESEARCH_HISTORY: "Reviewed research history", SEARCH_HISTORICAL_TEXT: "Historical text search · SBERT", SEARCH_HISTORICAL_IMAGES: "Historical image search · CLIP", SEARCH_WEB: "Public web search · SerpApi / Google", SEARCH_NEWS: "News search · SerpApi / Google News", SEARCH_IMAGES: "Image search · SerpApi / Google Images", STOP: "Stopped research" };
const statusIcon = (status: string) => status === "COMPLETED" || status === "SKIPPED" ? <Check size={13}/> : status === "FAILED" ? <TriangleAlert size={13}/> : status === "RUNNING" ? <RefreshCw size={13} className="agent-spin"/> : <Circle size={12}/>;

export function InvestigationAgentPanel({ investigationId, onResearchUpdated }: { investigationId: string; onResearchUpdated: () => void }) {
  const [objective, setObjective] = useState(""); const [runs, setRuns] = useState<AgentRun[]>([]); const [run, setRun] = useState<AgentRun | null>(null);
  const [actions, setActions] = useState<AgentAction[]>([]); const [error, setError] = useState(""); const [busy, setBusy] = useState(false); const [maxIterations, setMaxIterations] = useState(5); const [maxQueries, setMaxQueries] = useState(10);
  const refreshHistory = useCallback(async () => { const data = await api.agentRuns(investigationId); setRuns(data.items); }, [investigationId]);
  useEffect(() => { refreshHistory().catch((e: Error) => setError(e.message)); }, [refreshHistory]);
  useEffect(() => {
    if (!run || !["QUEUED", "RUNNING"].includes(run.status)) return;
    let disposed = false; let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const [updated, trace] = await Promise.all([api.agentRun(run.id), api.agentActions(run.id)]);
        if (disposed) return;
        setRun(updated); setActions(trace.items);
        if (["QUEUED", "RUNNING"].includes(updated.status)) timer = setTimeout(poll, 1200);
        else { await refreshHistory(); onResearchUpdated(); }
      } catch (e) { if (!disposed) setError((e as Error).message); }
    };
    timer = setTimeout(poll, 500);
    return () => { disposed = true; clearTimeout(timer); };
  }, [run?.id, run?.status, refreshHistory, onResearchUpdated]);
  async function loadRun(id: string) { setError(""); try { const [data, trace] = await Promise.all([api.agentRun(id), api.agentActions(id)]); setRun(data); setActions(trace.items); } catch (e) { setError((e as Error).message); } }
  async function start(event: FormEvent) { event.preventDefault(); if (!objective.trim()) return; setBusy(true); setError(""); try { const created = await api.startAgent(investigationId, objective.trim(), { max_iterations: maxIterations, max_serpapi_queries: maxQueries }); setRun(created); setActions([]); setObjective(""); await refreshHistory(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }
  async function stop() { if (!run) return; setBusy(true); try { const stopped = await api.stopAgent(run.id); setRun(stopped); await loadRun(run.id); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }
  const running = run ? ["QUEUED", "RUNNING"].includes(run.status) : false;
  const progress = run ? Math.min(100, Math.round((run.actions_completed / Math.max(run.max_actions, 1)) * 100)) : 0;
  const coverage = run?.research_summary || {};
  return <section className="agent-section"><div className="section-head"><div><span className="eyebrow">BOUNDED RESEARCH ORCHESTRATION</span><h3>Investigation Agent</h3></div><span className={`agent-status ${run?.status?.toLowerCase() || "ready"}`}>{run?.status || "READY"}</span></div>
    <div className="agent-card"><form className="agent-start-form" onSubmit={start}><label>Objective<textarea rows={2} maxLength={1000} value={objective} onChange={(e) => setObjective(e.target.value)} placeholder="Describe the research question for this investigation"/></label><div className="agent-controls"><label>Iterations<input type="number" min={1} max={20} value={maxIterations} onChange={(e) => setMaxIterations(Number(e.target.value))}/></label><label>SerpApi queries<input type="number" min={0} max={50} value={maxQueries} onChange={(e) => setMaxQueries(Number(e.target.value))}/></label><button className="button" disabled={busy || running || !objective.trim()}><Play size={14}/>{busy ? "Starting…" : "Start investigation"}</button>{running&&<button type="button" className="button secondary" onClick={stop} disabled={busy}><Square size={13}/> Stop run</button>}</div></form>
      {error&&<p className="error">{error}</p>}{run&&<>
        <div className="agent-progress-head"><div><span className="eyebrow">CURRENT ACTIVITY</span><p>{running ? actions.find((item)=>item.status==="RUNNING")?.reason || "Preparing the next bounded research action…" : run.research_message || `Research stopped · ${run.stop_reason || run.status}`}</p></div><span>{run.iteration} / {run.max_iterations} iterations</span></div>
        <div className="agent-progress"><div style={{width:`${progress}%`}}/></div><div className="agent-progress-meta"><span>{run.actions_completed} / {run.max_actions} actions</span><span>{run.queries_used} / {run.max_serpapi_queries} SerpApi queries</span><span>{run.results_collected} results collected</span></div>
        {actions.some((item)=>item.output_summary.demo_mode===true)&&<p className="demo-research-label">DEMO / MOCK DATA · NOT LIVE WEB RESULTS</p>}
        <div className="agent-stats"><div><small>Sources discovered</small><strong>{run.sources_discovered}</strong></div><div><small>Historical matches</small><strong>{run.historical_matches}</strong></div><div><small>Web results</small><strong>{run.web_results}</strong></div><div><small>News results</small><strong>{run.news_results}</strong></div><div><small>Image results</small><strong>{run.image_results}</strong></div></div>
        <div className="agent-coverage"><span className="eyebrow">RESEARCH COVERAGE</span><div>{[["SEARCH_HISTORICAL_TEXT","Historical Cases"],["SEARCH_HISTORICAL_IMAGES","Historical Images"],["SEARCH_WEB","Public Web"],["SEARCH_NEWS","News"],["SEARCH_IMAGES","Images"]].map(([key,label])=><span key={key} className={coverage[key]===true?"covered":coverage[key]===false?"coverage-failed":"coverage-pending"}>{coverage[key]===true?<Check size={13}/>:coverage[key]===false?<TriangleAlert size={13}/>:<Circle size={12}/>} {label}</span>)}</div></div>
        {actions.some((item)=>Array.isArray(item.output_summary.matches)&&item.output_summary.matches.length>0)&&<details className="agent-matches"><summary>Historical research leads · {run.historical_matches}</summary><div>{actions.flatMap((item)=>Array.isArray(item.output_summary.matches)?item.output_summary.matches as Array<Record<string,unknown>>:[]).map((match,index)=><article key={`${String(match.historical_case_id)}-${index}`}><strong>{String(match.title||"Historical case")}</strong><small>{match.match_type==="SEMANTIC_SIMILARITY"?"Semantic similarity":"Visual similarity"} · {String(match.similarity_score??match.visual_similarity??"—")} · Requires investigator verification</small><code>{String(match.historical_case_id||match.image_id||"")}</code></article>)}</div></details>}
        <details className="agent-trace" open={running}><summary>Research Action Trace · {actions.length} actions</summary>{actions.length ? <ol>{actions.map((action)=><li key={action.id} className={`trace-${action.status.toLowerCase()}`}><span className="trace-icon">{statusIcon(action.status)}</span><div><strong>{String(action.sequence_number).padStart(2,"0")} · {labels[action.action_type] || action.action_type}</strong><p>{action.output_summary.message as string || action.error_message || action.reason}</p>{typeof action.input_payload.query==="string"&&<small>Query · {action.input_payload.query}</small>}{action.research_run_id&&<small>Research run · {action.research_run_id}</small>}</div></li>)}</ol>:<p className="research-empty">The run has not recorded an action yet.</p>}</details>
      </>}
    </div>
    <div className="agent-history"><div className="research-subhead"><span className="eyebrow">AGENT RUN HISTORY</span><span>{runs.length}</span></div>{runs.map((item)=><button key={item.id} className={item.id===run?.id?"research-run active":"research-run"} onClick={()=>loadRun(item.id)}><strong>{item.objective}</strong><small>{item.status} · {item.actions_completed} actions · {item.sources_discovered} sources · {item.stop_reason || "In progress"}</small></button>)}</div>
  </section>;
}

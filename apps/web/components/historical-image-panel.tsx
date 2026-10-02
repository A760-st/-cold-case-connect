"use client";
import { useEffect, useState } from "react";
import { ExternalLink, Image as ImageIcon, Search, X } from "lucide-react";
import { api } from "@/lib/api";
import type { Evidence, HistoricalImageSearchResult, HistoricalIndexStatus } from "@/lib/types";

function safeUrl(value: string | null) {
  if (!value) return null;
  try { const url = new URL(value); return url.protocol === "https:" || url.protocol === "http:" ? url.href : null; } catch { return null; }
}

export function HistoricalImagePanel({ investigationId, refreshKey = 0 }: { investigationId: string; refreshKey?: number }) {
  const [evidence, setEvidence] = useState<Evidence[] | null>(null);
  const [index, setIndex] = useState<HistoricalIndexStatus["historical_image_index"] | null>(null);
  const [selected, setSelected] = useState("");
  const [topK, setTopK] = useState(10);
  const [result, setResult] = useState<HistoricalImageSearchResult | null>(null);
  const [detail, setDetail] = useState<HistoricalImageSearchResult["results"][number] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    api.evidence(investigationId, { type: "IMAGE" }).then(rows => { if (live) { setEvidence(rows); setSelected(current => rows.some(row => row.id === current) ? current : ""); } }).catch((e: Error) => { if (live) setError(e.message); });
    api.historicalIndexStatus().then(value => { if (live) setIndex(value.historical_image_index); }).catch(() => { if (live) setIndex(null); });
    return () => { live = false; };
  }, [investigationId, refreshKey]);
  async function search() {
    if (!selected) return;
    setBusy(true); setError(""); setResult(null);
    try { setResult(await api.searchInvestigationHistoricalImages(investigationId, selected, topK)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="historical-section"><div className="section-head"><div><span className="eyebrow">VISUAL RETRIEVAL</span><h3>Historical Image Retrieval</h3></div></div><div className="historical-panel">
    <div className="historical-toolbar"><div><strong>Search historical images</strong><p>Choose one image evidence item. CLIP similarity is a research signal and requires verification.</p></div><label>Results<select value={topK} onChange={event => setTopK(Number(event.target.value))}>{[5, 10, 20].map(value => <option key={value} value={value}>{value}</option>)}</select></label></div>
    <div className={`index-state ${index?.status === "READY" ? "ready" : "degraded"}`}><span className="index-dot"/><span>{index ? `${index.status === "NO_CORPUS" ? "No historical image corpus available" : `Image index ${index.status.toLowerCase().replaceAll("_", " ")} · ${index.historical_image_count.toLocaleString()} images · ${index.embedding_model}`}` : "Historical image index status unavailable"}</span></div>
    {index?.status === "NO_CORPUS" && <p className="no-image-corpus">Text-based historical retrieval is available through Historical Matches. Image retrieval will be available when local historical image records are supplied and indexed.</p>}
    {error && <p className="error">{error}</p>}
    {evidence === null && <p className="hint">Loading image evidence…</p>}
    {evidence?.length === 0 && <p className="hint">Add JPEG, PNG, or WebP image evidence to search the historical image index.</p>}
    {!!evidence?.length && <div className="image-evidence-picker">{evidence.map(item => <button type="button" className={`image-evidence-choice ${selected === item.id ? "selected" : ""}`} key={item.id} onClick={() => { setSelected(item.id); setResult(null); }} aria-pressed={selected === item.id}><img src={api.evidenceContentUrl(item.id)} alt=""/><span><strong>{item.title}</strong><small>{item.original_filename || item.mime_type || "Image evidence"}</small></span><span className="image-choice-indicator" aria-hidden="true">{selected === item.id ? "Selected" : "Select"}</span></button>)}</div>}
    <div className="historical-run"><span>{selected ? "1 image evidence item selected" : "Select image evidence to begin"}</span><button className="button" disabled={busy || !selected || index?.status !== "READY"} onClick={search}><Search size={15}/>{busy ? "Searching…" : "Search Historical Images"}</button></div>
    {index && index.status !== "READY" && index.status !== "NO_CORPUS" && <p className="index-message">Image search is disabled until the historical image index is ready.</p>}
    {busy && <div className="loading-box historical-loading"><span>Validating selected image evidence…</span><span>Generating CLIP visual embedding…</span><span>Retrieving potentially similar historical images…</span></div>}
    {result && <div className="historical-results"><div className="retrieval-note"><strong>Potentially Similar Historical Images</strong><span>Visual Similarity · {result.model} · Similarity does not establish that images depict the same person, object, or event.</span><small>Search evidence: {result.query_source.title || "Selected image evidence"}</small></div>{!result.results.length ? <div className="no-results"><strong>No historical images were retrieved.</strong><p>Review historical image corpus coverage. Text-based historical retrieval remains available.</p></div> : <div className="historical-image-grid">{result.results.map(row => <button type="button" className="historical-image-card" key={row.image_id} onClick={() => setDetail(row)}>{row.image_content_url ? <img src={api.historicalImageContentUrl(row.image_id)} alt="Historical source image"/> : <span className="image-unavailable"><ImageIcon size={22}/>Preview unavailable</span>}<span className="historical-image-card-body"><strong>{row.title}</strong><small>{[row.location, row.date, row.case_type].filter(Boolean).join(" · ") || "No additional case details in source record"}</small><span>Visual Similarity <b>{row.visual_similarity.toFixed(3)}</b></span><span className="source-link">{row.source.name || "Source not provided by dataset"}{safeUrl(row.source.url || row.source.image_url) && <ExternalLink size={12}/>}</span></span></button>)}</div>}</div>}
  </div>{detail && <div className="overlay" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) setDetail(null); }}><section className="dialog detail-dialog" role="dialog" aria-modal="true"><header className="dialog-head"><div><span className="eyebrow">HISTORICAL IMAGE · SOURCE RECORD</span><h2>{detail.title}</h2></div><button className="icon-button" onClick={() => setDetail(null)} aria-label="Close"><X size={18}/></button></header>{detail.image_content_url && <img className="historical-image-large" src={api.historicalImageContentUrl(detail.image_id)} alt="Historical source image"/>}<div className="case-detail-grid">{[["DATE", detail.date], ["LOCATION", detail.location], ["CASE TYPE", detail.case_type], ["VISUAL SIMILARITY", detail.visual_similarity.toFixed(3)], ["SOURCE", detail.source.name || "Not provided by dataset"]].map(([label, value]) => <div key={label}><span className="eyebrow">{label}</span><p>{value}</p></div>)}</div><div className="retrieved-because"><span className="eyebrow">RETRIEVED USING</span><p>{result?.query_source.title || "Selected image evidence"}</p><small>CLIP visual similarity is a retrieval signal and does not establish identity or a factual connection.</small></div>{safeUrl(detail.source.url || detail.source.image_url) && <a className="button secondary download" href={safeUrl(detail.source.url || detail.source.image_url)!} target="_blank" rel="noreferrer">Open source record <ExternalLink size={14}/></a>}</section></div>}</section>;
}

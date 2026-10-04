import "./landing.css";
import { ArrowRight, ArrowUpRight, ArrowUpRightFromSquare, Plus, ShieldCheck } from "lucide-react";
import Link from "next/link";

type InvestigationSummary = {
  id: string;
  title: string;
  description: string;
  status: string;
  updated_at: string;
};

type ApiStatus = "CONNECTED" | "DEGRADED" | "OFFLINE";

async function readJson(url: string) {
  try {
    const response = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(2500) });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

async function getWorkspaceData() {
  const apiRoot = (process.env.API_INTERNAL_URL || process.env.NEXT_PUBLIC_API_URL?.replace(/\/api\/v1$/, "") || "http://localhost:8001").replace(/\/$/, "");
  const apiBase = `${apiRoot}/api/v1`;
  const [rootHealth, workspaceHealth, investigationsResponse] = await Promise.all([
    readJson(`${apiRoot}/health`),
    readJson(`${apiBase}/health`),
    readJson(`${apiBase}/investigations`),
  ]);
  const investigations = investigationsResponse?.success && Array.isArray(investigationsResponse.data)
    ? investigationsResponse.data as InvestigationSummary[]
    : null;
  const apiStatus: ApiStatus = !rootHealth
    ? "OFFLINE"
    : workspaceHealth?.data?.status === "degraded"
      ? "DEGRADED"
      : "CONNECTED";

  return {
    apiStatus,
    investigations: investigations ? [...investigations].sort((a, b) => b.updated_at.localeCompare(a.updated_at)) : null,
    historicalCaseCount: typeof workspaceHealth?.data?.historical_case_count === "number"
      ? workspaceHealth.data.historical_case_count
      : null,
    historicalIndexStatus: typeof workspaceHealth?.data?.vector_index_status === "string"
      ? workspaceHealth.data.vector_index_status
      : "UNAVAILABLE",
  };
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric" }).format(new Date(value));
}

export default async function Home() {
  const workspace = await getWorkspaceData();
  const investigations = workspace.investigations;
  const activeCount = investigations?.filter(item => item.status === "ACTIVE").length ?? null;
  const recentInvestigations = investigations?.slice(0, 3) ?? [];

  return <main className="landing-page">
    <header className="landing-header">
      <Link className="landing-brand" href="/" aria-label="ColdSync home">
        <span className="landing-brandmark">C</span>
        <span><strong>COLDSYNC</strong><small>INVESTIGATIVE WORKSPACE</small></span>
      </Link>
      <nav className="landing-nav" aria-label="Primary navigation">
        <Link href="/investigations">Casework</Link>
        <Link href="/dashboard">Dashboard</Link>
      </nav>
      <div className="landing-header-actions">
        <span className={`landing-api-state ${workspace.apiStatus.toLowerCase()}`}><i aria-hidden="true"/> API {workspace.apiStatus}</span>
        <Link className="landing-new-button" href="/investigations/new"><Plus size={16}/> New investigation</Link>
      </div>
    </header>

    <section className="landing-hero" id="overview">
      <div className="landing-intro">
        <div className="landing-eyebrow"><span>RESEARCH / ARCHIVE / EVIDENCE</span><span>VOL. 01</span></div>
        <h1>ColdSync<span className="landing-full-stop">.</span><small>Evidence with its context intact.</small></h1>
        <p className="landing-lede">A casework space for organizing source material, tracing provenance, and reviewing potential conflicts without turning leads into conclusions.</p>
        <div className="landing-primary-actions">
          <Link className="landing-primary-button" href="/investigations/new">Start an investigation <ArrowUpRight size={16}/></Link>
          <Link className="landing-secondary-link" href="/investigations">Browse casework <ArrowRight size={16}/></Link>
        </div>
        <div className="landing-caution"><ShieldCheck size={16}/><span>Research support only. Investigators remain responsible for verification and decisions.</span></div>
      </div>

      <aside className="landing-casework" id="casework" aria-labelledby="casework-title">
        <header className="landing-casework-header">
          <div><span className="landing-section-label">WORKSPACE / 01</span><h2 id="casework-title">Recent casework</h2></div>
          <Link href="/investigations" aria-label="View all investigations"><ArrowUpRightFromSquare size={17}/></Link>
        </header>
        <div className="landing-casework-meta">
          <span>{investigations === null ? "CASE LIST UNAVAILABLE" : `${investigations.length} INVESTIGATION${investigations.length === 1 ? "" : "S"}`}</span>
          <span className={`landing-state-text ${workspace.apiStatus.toLowerCase()}`}>{workspace.apiStatus}</span>
        </div>
        {investigations === null ? <div className="landing-casework-empty"><p>Casework could not be loaded.</p><Link href="/investigations">Open investigations <ArrowRight size={14}/></Link></div>
          : recentInvestigations.length === 0 ? <div className="landing-casework-empty"><p>No investigations in this workspace yet.</p><Link href="/investigations/new">Create the first case <ArrowRight size={14}/></Link></div>
            : <div className="landing-case-list">{recentInvestigations.map((item, index) => <Link className="landing-case-row" href={`/investigations/${item.id}`} key={item.id}>
              <span className="landing-case-index">0{index + 1}</span>
              <span className="landing-case-main"><strong>{item.title}</strong><small>{item.description || "No case summary recorded."}</small></span>
              <span className={`landing-case-status ${item.status.toLowerCase()}`}>{item.status.replaceAll("_", " ")}</span>
              <span className="landing-case-date">{formatDate(item.updated_at)}</span>
              <ArrowUpRight size={15} className="landing-case-arrow"/>
            </Link>)}</div>}
        <footer className="landing-casework-footer"><span><i/> SOURCE-AWARE CASEWORK</span><Link href="/investigations">Full register <ArrowRight size={14}/></Link></footer>
      </aside>
    </section>

    <section className="landing-pulse" aria-label="Workspace status">
      <div className="landing-pulse-heading"><span className="landing-section-label">LIVE WORKSPACE</span><span className="landing-pulse-rule"/></div>
      <div className="landing-metrics">
        <div className="landing-metric"><span>Active investigations</span><strong>{activeCount === null ? "—" : String(activeCount).padStart(2, "0")}</strong><small>{investigations === null ? "Unavailable" : `${investigations.length} total case${investigations.length === 1 ? "" : "s"}`}</small></div>
        <div className="landing-metric"><span>Historical records</span><strong>{workspace.historicalCaseCount === null ? "—" : workspace.historicalCaseCount.toLocaleString("en")}</strong><small>Indexed source records</small></div>
        <div className="landing-metric"><span>Text index</span><strong className="landing-index-state">{workspace.historicalIndexStatus.replaceAll("_", " ")}</strong><small>Search availability</small></div>
      </div>
    </section>

    <section className="landing-review-note" id="review">
      <span className="landing-review-mark" aria-hidden="true">C / 01</span>
      <p>Potential connections stay connected to their sources. Contradictions remain open for human review; no automated finding determines guilt or responsibility.</p>
      <Link href="/dashboard">Open dashboard <ArrowUpRight size={15}/></Link>
    </section>

    <footer className="landing-footer"><span>COLDSYNC AI · INVESTIGATIVE RESEARCH SUPPORT</span><Link href="/investigations">Enter workspace <ArrowRight size={14}/></Link></footer>
  </main>;
}

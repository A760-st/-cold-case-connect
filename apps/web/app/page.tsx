import { ArrowUpRight, Activity, Search, Network, ShieldCheck, Plus } from "lucide-react";
import Link from "next/link";

async function getHealth() {
  const api = process.env.NEXT_PUBLIC_API_URL?.replace(/\/api\/v1$/, "") || "http://localhost:8001";
  try {
    const response = await fetch(`${api}/health`, { cache: "no-store", signal: AbortSignal.timeout(2000) });
    return response.ok ? "CONNECTED" : "DEGRADED";
  } catch { return "OFFLINE"; }
}

export default async function Home() {
  const health = await getHealth();
  return <main className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="brandmark">C</div><div><strong>COLDSYNC</strong><small>INVESTIGATIVE WORKSPACE</small></div></div>
      <div className="nav-label">WORKSPACE</div>
      <a className="nav active" href="#overview"><Activity size={17}/> Overview</a>
      <a className="nav" href="#investigations"><Search size={17}/> Investigations</a>
      <a className="nav" href="#graph"><Network size={17}/> Evidence graph</a>
      <div className="sidebar-bottom"><div className="responsible"><ShieldCheck size={17}/><span>Research support only<br/><small>Human verification required</small></span></div><div className="version">FOUNDATION BUILD · 0.1.0</div></div>
    </aside>
    <section className="content">
      <header className="topbar"><div><span className="eyebrow">INVESTIGATOR CONSOLE</span><h1>Research with context.</h1></div><div className="health"><span className={health === "CONNECTED" ? "dot" : "dot muted"}></span> API {health}</div></header>
      <div className="hero"><div className="hero-copy"><div className="eyebrow accent">EVIDENCE · HISTORY · PUBLIC SOURCES</div><h2>Connect evidence.<br/><em>Discover connections.</em></h2><p>An investigative research workspace that helps organize case information and connect it to historical records and public sources. Investigators remain responsible for verification and decisions.</p><a className="button" href="#investigations"><Plus size={17}/> Start investigation <ArrowUpRight size={15}/></a></div><div className="hero-art"><div className="orbit orbit-one"></div><div className="orbit orbit-two"></div><div className="core">CS</div><span className="node n1">CASE</span><span className="node n2">SOURCE</span><span className="node n3">EVIDENCE</span><span className="node n4">HISTORY</span></div></div>
      <div className="overview-grid"><div className="overview-card"><div className="empty-icon"><Search size={19}/></div><h3>Case-centered research</h3><p>Keep investigation context organized as future analysis tools connect evidence, history, and public sources.</p></div><div className="overview-card"><div className="empty-icon"><Network size={19}/></div><h3>Traceable connections</h3><p>Planned workflows will make sources and evidence behind each connection visible for investigator review.</p></div><div className="overview-card"><div className="empty-icon"><ShieldCheck size={19}/></div><h3>Human verification</h3><p>ColdSync supports research and evidence organization. Investigators retain interpretation and decision-making.</p></div></div>
      <div className="section-head" id="investigations"><div><span className="eyebrow">YOUR WORKSPACE</span><h3>Ready to begin?</h3></div></div>
      <div className="empty"><div className="empty-icon"><Search size={21}/></div><h4>Start with an investigation</h4><p>Create a case workspace to record an investigation and its initial context.</p><Link className="button" href="/investigations/new"><Plus size={17}/> Start investigation <ArrowUpRight size={15}/></Link><Link className="text-link" href="/dashboard">Open dashboard</Link></div>
      <footer>ColdSync AI is an investigative research and evidence-organization system. It does not determine guilt, identify perpetrators, or replace professional investigators.</footer>
    </section>
  </main>;
}

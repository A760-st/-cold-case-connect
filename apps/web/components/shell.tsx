import Link from "next/link";
import { Activity, Search, Network, ShieldCheck } from "lucide-react";

export function Shell({ children }: { children: React.ReactNode }) {
  return <main className="shell"><aside className="sidebar"><Link href="/" className="brand"><div className="brandmark">C</div><div><strong>COLDSYNC</strong><small>INVESTIGATIVE WORKSPACE</small></div></Link><div className="nav-label">WORKSPACE</div><Link className="nav" href="/dashboard"><Activity size={17}/> Dashboard</Link><Link className="nav" href="/investigations"><Search size={17}/> Investigations</Link><div className="sidebar-bottom"><div className="responsible"><ShieldCheck size={17}/><span>Research support only<br/><small>Human verification required</small></span></div><div className="version">FOUNDATION BUILD · 0.2.0</div></div></aside><section className="content">{children}<footer>ColdSync AI organizes investigative research. It does not determine guilt, identify perpetrators, or replace professional investigators.</footer></section></main>;
}

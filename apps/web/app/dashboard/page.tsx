"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Plus, ArrowUpRight } from "lucide-react";
import { Shell } from "@/components/shell";
import { api } from "@/lib/api";
import type { Investigation } from "@/lib/types";

export default function Dashboard() {
  const [items, setItems] = useState<Investigation[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.investigations().then(setItems).catch((e: Error) => setError(e.message)); }, []);
  const active = items?.filter(x => x.status === "ACTIVE").length ?? 0;
  const complete = items?.filter(x => x.status === "COMPLETED").length ?? 0;
  return <Shell><header className="topbar"><div><span className="eyebrow">INVESTIGATOR CONSOLE</span><h1>Dashboard</h1></div><Link className="button" href="/investigations/new"><Plus size={16}/> New investigation</Link></header>
    {error && <p className="error">{error}</p>}{items === null && !error && <p className="hint">Loading investigations...</p>}
    {items && <><div className="stats"><Stat label="Total investigations" value={items.length}/><Stat label="Active" value={active}/><Stat label="Completed" value={complete}/></div><div className="section-head"><div><span className="eyebrow">WORKSPACE</span><h3>Recent investigations</h3></div><Link className="text-link" href="/investigations">View all <ArrowUpRight size={14}/></Link></div>{items.length === 0 ? <Empty/> : <div className="list">{items.slice(0,5).map(item => <Link key={item.id} href={`/investigations/${item.id}`} className="row"><div><strong>{item.title}</strong><small>{item.description || "No description provided"}</small></div><Status value={item.status}/><time>{new Date(item.updated_at).toLocaleDateString()}</time></Link>)}</div>}</>}
  </Shell>;
}
function Stat({label,value}:{label:string;value:number}){return <div className="stat"><small>{label}</small><strong>{value}</strong></div>}
function Status({value}:{value:string}){return <span className="status">{value}</span>}
function Empty(){return <div className="empty"><h4>No investigations yet</h4><p>Create your first investigation to begin organizing case research.</p><Link href="/investigations/new" className="button"><Plus size={16}/> Create investigation</Link></div>}

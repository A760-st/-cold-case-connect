"use client";
import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { Shell } from "@/components/shell";
import { api } from "@/lib/api";
import type { Investigation } from "@/lib/types";

export default function NewInvestigation(){const router=useRouter();const [title,setTitle]=useState("");const [description,setDescription]=useState("");const [error,setError]=useState("");const [saving,setSaving]=useState(false);async function submit(e:FormEvent){e.preventDefault();setError("");setSaving(true);try{const item=await api.post<Investigation>("/investigations",{title:title.trim(),description:description.trim()});router.push(`/investigations/${item.id}`)}catch(e){setError((e as Error).message);setSaving(false)}}return <Shell><Link className="back" href="/investigations"><ArrowLeft size={15}/> Investigations</Link><header className="topbar"><div><span className="eyebrow">NEW CASEWORK</span><h1>Create investigation</h1></div></header><form className="form-card" onSubmit={submit}><label>Investigation title <span>Required</span><input required maxLength={240} value={title} onChange={e=>setTitle(e.target.value)} placeholder="e.g. Unidentified Historical Incident"/></label><label>Case description <span>Optional</span><textarea maxLength={10000} rows={6} value={description} onChange={e=>setDescription(e.target.value)} placeholder="Add known context, location, approximate date, and initial questions."/></label>{error&&<p className="error">{error}</p>}<div className="form-actions"><Link className="button secondary" href="/investigations">Cancel</Link><button className="button" disabled={saving||!title.trim()}>{saving?"Creating…":"Create investigation"}</button></div></form></Shell>}

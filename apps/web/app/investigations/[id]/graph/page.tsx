"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { Shell } from "@/components/shell";
import { InvestigationGraphExplorer } from "@/components/investigation-graph";

export default function InvestigationGraphPage(){
 const {id}=useParams<{id:string}>();
 return <Shell><Link className="back" href={`/investigations/${id}`}><ArrowLeft size={15}/> Investigation</Link><InvestigationGraphExplorer investigationId={id}/></Shell>;
}

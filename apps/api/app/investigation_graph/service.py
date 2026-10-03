import hashlib
import json
from datetime import date, datetime, timezone
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models.agent import AgentAction, AgentRun
from app.models.correlation import Correlation, CorrelationReview
from app.models.evidence import Evidence
from app.models.geospatial import Contradiction, EvidenceLocation, HistoricalCaseLocation, Location, SourceLocation, TimelineEventLocation
from app.models.historical_case import HistoricalCase
from app.models.historical_case_image import HistoricalCaseImage
from app.models.investigation import Investigation
from app.models.investigation_graph import Claim, ClaimStatus, ClaimType, GraphBookmark, GraphNote, SourceRelationship, SourceRelationshipType
from app.models.research_intelligence import InvestigationQuestion, ResearchGap
from app.models.timeline import TimelineEvent, TimelineEventEvidence, TimelineEventSource
from app.models.web_research import ResearchRun, ResearchSearch, WebSearchResult, WebSource

class GraphError(Exception):
    def __init__(self,code,status_code=404): self.code,self.status_code=code,status_code

def node_id(kind,identifier): return f"{kind.lower()}:{identifier}"
def edge_id(kind,source,target,record_id=None): return "edge:"+hashlib.sha256(f"{kind}|{source}|{target}|{record_id or ''}".encode()).hexdigest()[:28]

class InvestigationGraphService:
    EDGE_GROUPS={"PROVENANCE":{"CONTAINS","DERIVED_FROM","REPORTED_BY","FOUND_IN","PRODUCED_BY","SEARCHED_BY","SOURCE_OF","EXTRACTED_FROM","BELONGS_TO"},"ANALYTICAL":{"CORRELATES_WITH","SEMANTICALLY_SIMILAR","VISUALLY_SIMILAR","GEOGRAPHICALLY_OVERLAPS","TEMPORALLY_OVERLAPS","ENTITY_OVERLAP","POTENTIAL_CONNECTION","RELATED_TO"},"CONFLICT":{"CONFLICTS_WITH","DATE_CONFLICT","LOCATION_CONFLICT","ATTRIBUTE_CONFLICT","ENTITY_CONFLICT","TIMELINE_CONFLICT","SOURCE_CONFLICT","TIME_CONFLICT"},"RESEARCH":{"GENERATED","ADDRESSES","INVESTIGATES","RESPONDED_TO","DISCOVERED"},"INVESTIGATOR":{"REVIEWED_BY","MARKED_RELEVANT","MARKED_NOT_RELEVANT","REQUIRES_VERIFICATION","ADDED_BY_INVESTIGATOR"}}
    def __init__(self,db:Session): self.db=db

    def graph(self,investigation_id,*,node_types=None,edge_types=None,source_types=None,statuses=None,date_from=None,date_to=None,location_ids=None,claim_types=None,q=None,limit=250,edge_limit=600,offset=0):
        inv=self._investigation(investigation_id)
        nodes={};edges={};projection_truncated=False
        def bounded(statement,cap):
            nonlocal projection_truncated
            result=list(self.db.scalars(statement.limit(cap+1)))
            if len(result)>cap:
                projection_truncated=True
                result=result[:cap]
            return result
        def add_node(kind,identifier,label,metadata=None,created_at=None,category="PROVENANCE"):
            nid=node_id(kind,identifier)
            nodes.setdefault(nid,{"id":nid,"type":kind,"label":str(label or kind.replace("_"," "))[:220],"metadata":metadata or {},"created_at":created_at.isoformat() if hasattr(created_at,"isoformat") else created_at,"category":category})
            return nid
        def add_edge(kind,source,target,record_id=None,explanation="",metadata=None,category=None,created_by="SYSTEM",created_at=None,review_status=None,score=None):
            if source not in nodes or target not in nodes:return
            eid=edge_id(kind,source,target,record_id)
            edges.setdefault(eid,{"id":eid,"type":kind,"source":source,"target":target,"explanation":explanation,"created_by":created_by,"created_at":created_at.isoformat() if hasattr(created_at,"isoformat") else created_at,"score":score,"review_status":review_status,"category":category or self.edge_category(kind),"metadata":metadata or {}})
        inv_id=add_node("INVESTIGATION",inv.id,inv.title,{"status":inv.status.value,"updated_at":inv.updated_at.isoformat() if inv.updated_at else None},inv.created_at)
        evidence=bounded(select(Evidence).where(Evidence.investigation_id==investigation_id).order_by(Evidence.created_at.desc()),500)
        for row in evidence:
            eid=add_node("EVIDENCE",row.id,row.title,{"evidence_type":row.type.value,"processing_status":row.processing_status.value,"filename":row.original_filename,"description":row.description[:250]},row.created_at)
            add_edge("BELONGS_TO",eid,inv_id)
        claims=bounded(select(Claim).where(Claim.investigation_id==investigation_id),1000)
        sources=bounded(select(WebSource).where(WebSource.investigation_id==investigation_id),500)
        source_node_ids={node_id("SOURCE",row.id) for row in sources}
        for row in sources:
            sid=add_node("SOURCE",row.id,row.title or row.domain or row.source_name,{"domain":row.domain,"source_name":row.source_name,"source_type":row.source_type.value,"canonical_url":row.canonical_url,"first_seen_at":row.first_seen_at.isoformat() if row.first_seen_at else None,"last_seen_at":row.last_seen_at.isoformat() if row.last_seen_at else None},row.first_seen_at)
            add_edge("BELONGS_TO",sid,inv_id)
        results=bounded(select(WebSearchResult).where(WebSearchResult.investigation_id==investigation_id),1000)
        result_counts=dict(self.db.execute(select(WebSearchResult.research_run_id,func.count(WebSearchResult.id)).where(WebSearchResult.investigation_id==investigation_id).group_by(WebSearchResult.research_run_id)).all())
        for row in results:
            rid=add_node("SEARCH_RESULT",row.id,row.title or row.url,{"url":row.url,"search_type":row.result_type.value,"position":row.position,"published_at":row.published_at,"snippet":(row.snippet or "")[:300],"research_run_id":str(row.research_run_id)},row.created_at)
            add_edge("BELONGS_TO",rid,inv_id);add_edge("PRODUCED_BY",rid,node_id("RESEARCH_RUN",row.research_run_id))
            search=self.db.get(ResearchSearch,row.search_id)
            if search:
                qid=add_node("RESEARCH_SEARCH",search.id,search.query,{"query":search.query,"engine":search.engine,"search_type":search.search_type.value,"result_count":search.result_count,"status":search.status.value},search.created_at)
                add_edge("FOUND_IN",rid,qid);add_edge("SEARCHED_BY",qid,node_id("RESEARCH_RUN",search.research_run_id))
            if row.source_id:
                # A result's nullable polymorphic reference must not create a
                # source node by ID alone. The in-scope source query above is the
                # authoritative check for investigation ownership.
                source_id=node_id("SOURCE",row.source_id)
                if source_id in source_node_ids:
                    add_edge("SOURCE_OF",node_id("SEARCH_RESULT",row.id),source_id)
        research_runs=bounded(select(ResearchRun).where(ResearchRun.investigation_id==investigation_id),250)
        for row in research_runs:
            rr=add_node("RESEARCH_RUN",row.id,row.objective,{"trigger":row.trigger.value,"status":row.status.value,"result_count":result_counts.get(row.id,0),"completed_at":row.completed_at.isoformat() if row.completed_at else None},row.created_at)
            add_edge("BELONGS_TO",rr,inv_id)
            if row.agent_run_id:add_edge("GENERATED",rr,node_id("AGENT_RUN",row.agent_run_id))
        agent_runs=bounded(select(AgentRun).where(AgentRun.investigation_id==investigation_id),250)
        for row in agent_runs:
            ar=add_node("AGENT_RUN",row.id,row.objective,{"status":row.status.value,"iteration":row.iteration,"stop_reason":row.stop_reason,"action_count":row.actions_completed,"max_iterations":row.max_iterations,"max_queries":row.max_serpapi_queries},row.created_at)
            add_edge("BELONGS_TO",ar,inv_id)
        actions=bounded(select(AgentAction).where(AgentAction.investigation_id==investigation_id),1000)
        for row in actions:
            aid=add_node("AGENT_ACTION",row.id,row.action_type.value,{"action_type":row.action_type.value,"status":row.status.value,"reason":row.reason,"input":row.input_payload or {},"output_summary":row.output_summary or {}},row.created_at)
            add_edge("PRODUCED_BY",aid,node_id("AGENT_RUN",row.agent_run_id))
            if row.research_run_id:add_edge("GENERATED",aid,node_id("RESEARCH_RUN",row.research_run_id))
        historical_ids=set()
        for row in bounded(select(TimelineEvent.historical_case_id).where(TimelineEvent.investigation_id==investigation_id,TimelineEvent.historical_case_id.is_not(None)),500):historical_ids.add(row)
        for row in bounded(select(HistoricalCaseLocation.historical_case_id).join(Location).where(Location.investigation_id==investigation_id),500):historical_ids.add(row)
        related_image_ids=set()
        for row in bounded(select(Correlation).where(Correlation.investigation_id==investigation_id),1000):
            for object_type,object_id in ((row.source_type.value,row.source_id),(row.target_type.value,row.target_id)):
                if object_type=="HISTORICAL_CASE":historical_ids.add(object_id)
                elif object_type=="HISTORICAL_IMAGE":related_image_ids.add(object_id)
        if related_image_ids:
            for case_id in bounded(select(HistoricalCaseImage.historical_case_id).where(HistoricalCaseImage.id.in_(related_image_ids)),500):historical_ids.add(case_id)
        if historical_ids:
            for row in bounded(select(HistoricalCase).where(HistoricalCase.id.in_(historical_ids)),300):
                hid=add_node("HISTORICAL_CASE",row.id,row.title,{"date":row.case_date.isoformat() if row.case_date else None,"location":row.location,"case_type":row.case_type,"source_name":row.source_name,"source_url":row.source_url},row.created_at);add_edge("RELATED_TO",hid,inv_id)
                for image in bounded(select(HistoricalCaseImage).where(HistoricalCaseImage.historical_case_id==row.id),100):
                    iid=add_node("HISTORICAL_IMAGE",image.id,image.source_name or row.title,{"source_url":image.source_url,"image_url":image.image_url,"historical_case_id":str(row.id),"similarity":image.metadata_json.get("visual_similarity") if image.metadata_json else None},image.created_at);add_edge("DERIVED_FROM",iid,hid)
        events=bounded(select(TimelineEvent).where(TimelineEvent.investigation_id==investigation_id),500)
        for row in events:
            tid=add_node("TIMELINE_EVENT",row.id,row.title,{"date_start":row.date_start.isoformat() if row.date_start else None,"date_end":row.date_end.isoformat() if row.date_end else None,"date_text":row.date_text,"date_precision":row.date_precision.value,"event_type":row.event_type.value,"location":row.location,"status":row.status.value},row.created_at)
            add_edge("BELONGS_TO",tid,inv_id)
            for link in self.db.scalars(select(TimelineEventEvidence).where(TimelineEventEvidence.timeline_event_id==row.id)):add_edge("DERIVED_FROM",tid,node_id("EVIDENCE",link.evidence_id),link.relationship_type)
            for source in self.db.scalars(select(TimelineEventSource).where(TimelineEventSource.timeline_event_id==row.id)):
                skind="SEARCH_RESULT" if source.source_type.value.endswith("RESULT") else "HISTORICAL_CASE" if source.source_type.value=="HISTORICAL_CASE" else "EVIDENCE" if source.source_type.value=="EVIDENCE" else None
                if source.source_type.value=="SOURCE":skind="SOURCE"
                if skind:add_edge("DERIVED_FROM",tid,node_id(skind,source.source_id),source.relationship_type)
            for link in self.db.scalars(select(TimelineEventLocation).where(TimelineEventLocation.timeline_event_id==row.id)):add_edge("OCCURRED_AT",tid,node_id("LOCATION",link.location_id))
            if row.historical_case_id:add_edge("RELATED_TO",tid,node_id("HISTORICAL_CASE",row.historical_case_id))
        locations=bounded(select(Location).where(Location.investigation_id==investigation_id),500)
        for row in locations:
            lid=add_node("LOCATION",row.id,row.raw_text,{"normalized_name":row.normalized_name,"latitude":row.latitude,"longitude":row.longitude,"precision":row.precision.value,"geocoding_status":row.geocoding_status.value,"geocoding_source":row.geocoding_source,"city":row.city,"state":row.state},row.created_at)
            for link in self.db.scalars(select(EvidenceLocation).where(EvidenceLocation.location_id==row.id)):add_edge("LOCATED_AT",node_id("EVIDENCE",link.evidence_id),lid)
            for link in self.db.scalars(select(TimelineEventLocation).where(TimelineEventLocation.location_id==row.id)):add_edge("OCCURRED_AT",node_id("TIMELINE_EVENT",link.timeline_event_id),lid)
            for link in self.db.scalars(select(SourceLocation).where(SourceLocation.location_id==row.id)):add_edge("LOCATED_AT",node_id("SOURCE",link.source_id),lid)
            for link in self.db.scalars(select(HistoricalCaseLocation).where(HistoricalCaseLocation.location_id==row.id)):add_edge("LOCATED_AT",node_id("HISTORICAL_CASE",link.historical_case_id),lid)
        for claim in claims:self._claim_node(claim,add_node,add_edge)
        correlations=bounded(select(Correlation).where(Correlation.investigation_id==investigation_id),1000)
        for row in correlations:
            a=self._correlation_node_type(row.source_type.value);b=self._correlation_node_type(row.target_type.value)
            if a and b:
                an=node_id(a,row.source_id);bn=node_id(b,row.target_id)
                review=self.db.scalar(select(CorrelationReview).where(CorrelationReview.correlation_id==row.id))
                # Correlation references are polymorphic; only connect records that
                # were independently loaded from this investigation. Never create
                # placeholder nodes from unvalidated IDs.
                if an not in nodes or bn not in nodes: continue
                correlation_id=add_node("CORRELATION",row.id,row.correlation_type.value,{"correlation_type":row.correlation_type.value,"score":row.score,"confidence_label":row.confidence_label,"explanation":row.explanation,"review_status":review.review_status.value if review else "REQUIRES_VERIFICATION","evidence_basis":row.evidence_basis,"created_by":row.created_by.value},row.created_at,"ANALYTICAL")
                add_edge("CORRELATES_WITH",correlation_id,an,row.id,row.explanation,{"object_role":"source"},"ANALYTICAL",row.created_by.value,row.created_at,review.review_status.value if review else "REQUIRES_VERIFICATION",row.score)
                add_edge("CORRELATES_WITH",correlation_id,bn,row.id,row.explanation,{"object_role":"target"},"ANALYTICAL",row.created_by.value,row.created_at,review.review_status.value if review else "REQUIRES_VERIFICATION",row.score)
        contradictions=bounded(select(Contradiction).where(Contradiction.investigation_id==investigation_id),500)
        for row in contradictions:
            cid=add_node("CONTRADICTION",row.id,row.type.value,{"description":row.description,"status":row.status.value,"priority":row.priority,"severity":row.severity.value,"value_a":row.value_a,"value_b":row.value_b},row.created_at,"CONFLICT")
            add_edge("CONFLICTS_WITH",cid,node_id(self._record_node_type(row.source_a_type),row.source_a_id),row.id,row.description,category="CONFLICT");add_edge("CONFLICTS_WITH",cid,node_id(self._record_node_type(row.source_b_type),row.source_b_id),row.id,row.description,category="CONFLICT")
        gaps=bounded(select(ResearchGap).where(ResearchGap.investigation_id==investigation_id),500)
        for row in gaps:
            gid=add_node("RESEARCH_GAP",row.id,row.title,{"gap_type":row.gap_type.value,"description":row.description,"priority":row.priority,"status":row.status.value,"suggested_actions":row.suggested_research_actions,"last_agent_run_id":str(row.last_agent_run_id) if row.last_agent_run_id else None},row.created_at,"RESEARCH")
            add_edge("BELONGS_TO",gid,inv_id)
            for eid in row.related_evidence_ids or []:add_edge("ADDRESSES",node_id("EVIDENCE",eid),gid)
            for sid in row.related_source_ids or []:add_edge("ADDRESSES",node_id("SOURCE",sid),gid)
            for tid in row.related_timeline_event_ids or []:add_edge("ADDRESSES",node_id("TIMELINE_EVENT",tid),gid)
            for lid in row.related_location_ids or []:add_edge("ADDRESSES",node_id("LOCATION",lid),gid)
            for cid in row.related_contradiction_ids or []:add_edge("GENERATED",node_id("CONTRADICTION",cid),gid)
            if row.last_agent_run_id:add_edge("INVESTIGATES",node_id("AGENT_RUN",row.last_agent_run_id),gid)
        questions=bounded(select(InvestigationQuestion).where(InvestigationQuestion.investigation_id==investigation_id),300)
        for row in questions:
            qid=add_node("INVESTIGATIVE_QUESTION",row.id,row.question,{"status":row.status.value,"priority":row.priority,"last_agent_run_id":str(row.last_agent_run_id) if row.last_agent_run_id else None},row.created_at,"RESEARCH")
            add_edge("BELONGS_TO",qid,inv_id)
            for gid in row.related_gap_ids or []:add_edge("RELATED_TO",qid,node_id("RESEARCH_GAP",gid))
            if row.last_agent_run_id:add_edge("INVESTIGATES",node_id("AGENT_RUN",row.last_agent_run_id),qid)
        for row in bounded(select(SourceRelationship).where(SourceRelationship.investigation_id==investigation_id),500):
            add_edge(row.relationship_type.value,node_id("SOURCE",row.source_a_id),node_id("SOURCE",row.source_b_id),row.id,row.explanation,{"relationship_type":row.relationship_type.value,"created_by":row.created_by,"review_status":row.status},"INVESTIGATOR",row.created_by,row.created_at,row.status)
        for row in bounded(select(GraphNote).where(GraphNote.investigation_id==investigation_id),500):
            add_node("INVESTIGATOR_ACTION",row.id,"Investigator note",{"note":row.note,"created_by":row.created_by,"target_node":node_id(row.node_type,row.node_id)},row.created_at,"INVESTIGATOR");add_edge("ADDED_BY_INVESTIGATOR",node_id("INVESTIGATOR_ACTION",row.id),node_id(row.node_type,row.node_id),row.id,metadata={"created_by":row.created_by},category="INVESTIGATOR",created_by=row.created_by,created_at=row.created_at)
        counts={}
        for n in nodes.values():counts[n["type"]]=counts.get(n["type"],0)+1
        node_list=list(nodes.values());edge_list=list(edges.values())
        if q:
            matched={n["id"] for n in node_list if q.casefold() in (n["label"]+" "+json.dumps(n["metadata"],default=str)).casefold()}
            connected={x for e in edge_list if e["source"] in matched or e["target"] in matched for x in (e["source"],e["target"])}
            keep=matched|connected;node_list=[n for n in node_list if n["id"] in keep]
        if node_types:
            allowed={x.upper() for x in node_types};node_list=[n for n in node_list if n["type"] in allowed]
        selected_ids={x["id"] for x in node_list}
        if source_types:
            srcs={x.upper() for x in source_types};node_list=[n for n in node_list if n["type"] not in {"SEARCH_RESULT","SOURCE"} or n["metadata"].get("search_type",n["metadata"].get("source_type")) in srcs];selected_ids={x["id"] for x in node_list}
        if claim_types:node_list=[n for n in node_list if n["type"]!="CLAIM" or n["metadata"].get("claim_type") in {x.upper() for x in claim_types}];selected_ids={x["id"] for x in node_list}
        if statuses:
            allowed_statuses={x.upper() for x in statuses}
            matches={n["id"] for n in node_list if n["metadata"].get("status") and str(n["metadata"]["status"]).upper() in allowed_statuses}
            context={endpoint for edge in edge_list if edge["source"] in matches or edge["target"] in matches for endpoint in (edge["source"],edge["target"])}
            node_list=[n for n in node_list if n["id"] in matches|context]
            selected_ids={x["id"] for x in node_list}
        if location_ids:
            allowed={node_id("LOCATION",x) for x in location_ids};neighbors={e["source"] for e in edge_list if e["target"] in allowed}|{e["target"] for e in edge_list if e["source"] in allowed};selected_ids &= allowed|neighbors;node_list=[n for n in node_list if n["id"] in selected_ids]
        if date_from or date_to:
            date_ids=set()
            for n in node_list:
                val=n["metadata"].get("date_start") or n["metadata"].get("date") or n["metadata"].get("published_at")
                if val:
                    d=str(val)[:10]
                    if (not date_from or d>=date_from.isoformat()) and (not date_to or d<=date_to.isoformat()):date_ids.add(n["id"])
            selected_ids &= date_ids|{inv_id};node_list=[n for n in node_list if n["id"] in selected_ids]
        edge_list=[e for e in edge_list if e["source"] in selected_ids and e["target"] in selected_ids]
        if edge_types:
            allowed={x.upper() for x in edge_types}|{x.upper() for group in edge_types for x in self.EDGE_GROUPS.get(x.upper(),set())};edge_list=[e for e in edge_list if e["type"] in allowed or e["category"] in allowed]
        edge_counts={}
        for edge in edge_list:edge_counts[edge["type"]]=edge_counts.get(edge["type"],0)+1
        total_nodes,total_edges=len(node_list),len(edge_list)
        page_nodes=node_list[offset:offset+limit]
        page_ids={n["id"] for n in page_nodes}
        page_edges=[e for e in edge_list if e["source"] in page_ids and e["target"] in page_ids][:edge_limit]
        return {"nodes":page_nodes,"edges":page_edges,"metadata":{"investigation_id":str(inv.id),"title":inv.title,"generated_at":datetime.now(timezone.utc).isoformat(),"node_count":total_nodes,"edge_count":total_edges,"counts":counts,"edge_counts":edge_counts,"offset":offset,"limit":limit,"edge_limit":edge_limit,"truncated":projection_truncated or total_nodes>offset+limit or total_edges>len(page_edges)}}

    def _claim_node(self,claim,add_node,add_edge):
        cid=add_node("CLAIM",claim.id,f"{claim.subject} · {claim.object_value}",{"claim_type":claim.claim_type.value,"subject":claim.subject,"predicate":claim.predicate,"object_value":claim.object_value,"normalized_value":claim.normalized_value,"value_type":claim.value_type,"date_value":claim.date_value,"location_text":claim.location_text,"status":claim.status.value,"extraction_method":claim.extraction_method,"source_type":claim.source_type,"source_id":str(claim.source_id),"confidence_label":claim.confidence_label},claim.created_at)
        add_edge("BELONGS_TO",cid,node_id("INVESTIGATION",claim.investigation_id))
        if claim.evidence_id:add_edge("EXTRACTED_FROM",cid,node_id("EVIDENCE",claim.evidence_id))
        source_kind={"WEB_RESULT":"SEARCH_RESULT","NEWS_RESULT":"SEARCH_RESULT","IMAGE_RESULT":"SEARCH_RESULT","HISTORICAL_CASE":"HISTORICAL_CASE","EVIDENCE":"EVIDENCE","TIMELINE_EVENT":"TIMELINE_EVENT","INVESTIGATOR":"INVESTIGATION"}.get(claim.source_type,"SOURCE")
        add_edge("REPORTED_BY",cid,node_id(source_kind,claim.source_id))
        if claim.location_id:add_edge("LOCATED_AT",cid,node_id("LOCATION",claim.location_id))

    def _investigation(self,id):
        item=self.db.get(Investigation,id)
        if item is None:raise GraphError("INVESTIGATION_NOT_FOUND")
        return item
    @staticmethod
    def edge_category(kind):
        if "CONFLICT" in kind:return "CONFLICT"
        if kind in {"CORRELATES_WITH","SEMANTICALLY_SIMILAR","VISUALLY_SIMILAR","GEOGRAPHICALLY_OVERLAPS","TEMPORALLY_OVERLAPS","ENTITY_OVERLAP","POTENTIAL_CONNECTION","RELATED_TO"}:return "ANALYTICAL"
        if kind in {x.value for x in SourceRelationshipType}:return "INVESTIGATOR"
        if kind in {"GENERATED","ADDRESSES","INVESTIGATES","RESPONDED_TO","DISCOVERED"}:return "RESEARCH"
        if "INVESTIGATOR" in kind or kind.startswith("MARKED_") or kind=="REVIEWED_BY":return "INVESTIGATOR"
        return "PROVENANCE"
    @staticmethod
    def _record_node_type(kind):return {"EVIDENCE":"EVIDENCE","TIMELINE_EVENT":"TIMELINE_EVENT","WEB_RESULT":"SEARCH_RESULT","HISTORICAL_CASE":"HISTORICAL_CASE","SOURCE":"SOURCE"}.get(kind,"SOURCE")
    @staticmethod
    def _correlation_node_type(kind):return {"EVIDENCE":"EVIDENCE","HISTORICAL_CASE":"HISTORICAL_CASE","HISTORICAL_IMAGE":"HISTORICAL_IMAGE","WEB_RESULT":"SEARCH_RESULT","NEWS_RESULT":"SEARCH_RESULT","IMAGE_RESULT":"SEARCH_RESULT","SOURCE":"SOURCE"}.get(kind)

    def node(self,investigation_id,kind,identifier):
        graph=self.graph(investigation_id,limit=1000,edge_limit=3000)
        nid=node_id(kind,identifier);found=next((x for x in graph["nodes"] if x["id"]==nid),None)
        if not found:raise GraphError("GRAPH_NODE_NOT_FOUND")
        edges=[e for e in graph["edges"] if nid in {e["source"],e["target"]}];ids={nid}|{e["source"] for e in edges}|{e["target"] for e in edges}
        return {"node":found,"edges":edges,"connected_nodes":[x for x in graph["nodes"] if x["id"] in ids]}
    def neighborhood(self,investigation_id,kind,identifier,depth=1,max_nodes=100,node_types=None,edge_types=None):
        graph=self.graph(investigation_id,limit=1000,edge_limit=3000,node_types=None,edge_types=None);start=node_id(kind,identifier)
        if not any(n["id"]==start for n in graph["nodes"]):raise GraphError("GRAPH_NODE_NOT_FOUND")
        allowed_edges={x.upper() for x in edge_types or []}|{x.upper() for g in edge_types or [] for x in self.EDGE_GROUPS.get(x.upper(),set())};allowed_nodes={x.upper() for x in node_types or []}
        visited={start};frontier={start};edges=[]
        for _ in range(depth):
            next_nodes=set()
            for edge in graph["edges"]:
                if allowed_edges and edge["type"] not in allowed_edges and edge["category"] not in allowed_edges:continue
                if edge["source"] in frontier or edge["target"] in frontier:
                    edges.append(edge);other=edge["target"] if edge["source"] in frontier else edge["source"]
                    if other not in visited:next_nodes.add(other)
            next_nodes={x for x in next_nodes if not allowed_nodes or x.split(":",1)[0].upper() in allowed_nodes}
            next_nodes=list(next_nodes)[:max_nodes-len(visited)];visited.update(next_nodes);frontier=set(next_nodes)
            if not frontier:break
        ids={e["id"] for e in edges};return {"nodes":[n for n in graph["nodes"] if n["id"] in visited],"edges":[e for e in graph["edges"] if e["id"] in ids],"metadata":{"depth":depth,"truncated":len(visited)>=max_nodes}}

    def rebuild(self,investigation_id):
        self._investigation(investigation_id)
        # Graphs are deterministic projections; rebuild validates access and returns a fresh projection.
        graph=self.graph(investigation_id,limit=1000,edge_limit=3000)
        return {"status":"COMPLETED","idempotent":True,"node_count":graph["metadata"]["node_count"],"edge_count":graph["metadata"]["edge_count"],"generated_at":graph["metadata"]["generated_at"]}

    def extract_structured_claims(self,investigation_id):
        self._investigation(investigation_id);created=0;seen_fingerprints=set();truncated=False;processed_claims=0
        evidence_rows=list(self.db.scalars(select(Evidence).where(Evidence.investigation_id==investigation_id).order_by(Evidence.created_at.desc()).limit(501)))
        if len(evidence_rows)>500:truncated=True;evidence_rows=evidence_rows[:500]
        for evidence in evidence_rows:
            raw=(evidence.metadata_json or {}).get("claims",[])
            if not isinstance(raw,list):continue
            if len(raw)>100:truncated=True
            for item in raw[:100]:
                if processed_claims>=5000:truncated=True;break
                processed_claims+=1
                if not isinstance(item,dict):continue
                subject=item.get("subject");predicate=item.get("predicate");value=item.get("object_value",item.get("value"));kind=item.get("claim_type","OTHER")
                if not all(isinstance(x,str) and x.strip() for x in (subject,predicate,value)):continue
                try:kind=kind.upper()
                except AttributeError:continue
                if kind not in {x.value for x in ClaimType}:kind="OTHER"
                material=[str(evidence.id),kind,subject.strip().casefold(),predicate.strip().casefold(),value.strip().casefold()];fingerprint=hashlib.sha256(json.dumps(material,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
                if fingerprint in seen_fingerprints:continue
                seen_fingerprints.add(fingerprint)
                exists=self.db.scalar(select(Claim.id).where(Claim.investigation_id==investigation_id,Claim.fingerprint==fingerprint))
                if exists:continue
                claim=Claim(investigation_id=investigation_id,claim_type=kind,subject=subject.strip()[:500],predicate=predicate.strip()[:200],object_value=value.strip()[:4000],normalized_value=str(item.get("normalized_value"))[:4000] if item.get("normalized_value") is not None else None,value_type=str(item.get("value_type") or "TEXT")[:24],date_value=str(item.get("date_value"))[:40] if item.get("date_value") else None,location_text=str(item.get("location_text"))[:1000] if item.get("location_text") else None,confidence_label="UNKNOWN",extraction_method="STRUCTURED_EVIDENCE_METADATA",source_type="EVIDENCE",source_id=evidence.id,evidence_id=evidence.id,status="SOURCE_REPORTED",metadata_json={"metadata_path":"claims","source_text_preserved":True},fingerprint=fingerprint)
                self.db.add(claim);created+=1
            if processed_claims>=5000:truncated=True;break
        # Timeline dates and locations are already structured, source-linked
        # records. Preserve them as explicitly reported claims without parsing
        # free text or converting an investigator's note into a verified fact.
        events=list(self.db.scalars(select(TimelineEvent).where(TimelineEvent.investigation_id==investigation_id).order_by(TimelineEvent.created_at.desc()).limit(501)))
        if len(events)>500:truncated=True;events=events[:500]
        for event in events:
            values=[]
            linked_locations=set(self.db.scalars(select(TimelineEventLocation.location_id).join(Location,Location.id==TimelineEventLocation.location_id).where(TimelineEventLocation.timeline_event_id==event.id,Location.investigation_id==investigation_id)))
            claim_location_id=next(iter(linked_locations)) if len(linked_locations)==1 else None
            if event.date_start:
                value=event.date_text or event.date_start.isoformat()
                values.append((ClaimType.DATE,"reported event date",value,event.date_start.isoformat(),event.date_start.isoformat(),None))
            if event.location and event.location.strip():
                values.append((ClaimType.LOCATION,"reported location",event.location.strip(),event.location.strip(),None,event.location.strip()))
            for kind,predicate,value,normalized,date_value,location_text in values:
                if processed_claims>=5000:truncated=True;break
                processed_claims+=1
                material=[str(event.id),kind.value,event.title.strip().casefold(),predicate.casefold(),value.casefold()]
                fingerprint=hashlib.sha256(json.dumps(material,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
                if fingerprint in seen_fingerprints:continue
                seen_fingerprints.add(fingerprint)
                if self.db.scalar(select(Claim.id).where(Claim.investigation_id==investigation_id,Claim.fingerprint==fingerprint)):continue
                status=ClaimStatus.INVESTIGATOR_ADDED if event.status.value=="INVESTIGATOR_ADDED" else ClaimStatus.SOURCE_REPORTED
                claim=Claim(investigation_id=investigation_id,claim_type=kind,subject=event.title[:500],predicate=predicate,object_value=value[:4000],normalized_value=normalized,value_type=kind.value,date_value=date_value,location_text=location_text,location_id=claim_location_id if kind==ClaimType.LOCATION else None,confidence_label="UNKNOWN",extraction_method="STRUCTURED_TIMELINE_RECORD",source_type="TIMELINE_EVENT",source_id=event.id,status=status,metadata_json={"timeline_event_id":str(event.id),"date_precision":event.date_precision.value if kind==ClaimType.DATE else None},fingerprint=fingerprint)
                self.db.add(claim);created+=1
            if processed_claims>=5000:truncated=True;break
        self.db.commit();return {"created":created,"status":"COMPLETED","truncated":truncated}

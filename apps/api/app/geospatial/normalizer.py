import re
from app.models.geospatial import LocationPrecision

ALIASES={"bangalore":"bengaluru","bombay":"mumbai","calcutta":"kolkata","madras":"chennai"}
def normalize_location(raw:str)->str:
    value=" ".join((raw or "").split()).strip(" ,.;")
    if not value:return ""
    pieces=[p.strip() for p in value.split(",") if p.strip()]
    pieces[0]=ALIASES.get(pieces[0].casefold(),pieces[0])
    return ", ".join(pieces).casefold()

def infer_precision(raw:str, metadata:dict|None=None, has_coordinates:bool=False)->LocationPrecision:
    meta=metadata or {}; requested=meta.get("precision") or meta.get("location_precision")
    if isinstance(requested,str):
        try:return LocationPrecision(requested.upper())
        except ValueError:pass
    if has_coordinates:return LocationPrecision.EXACT_POINT
    text=" ".join((raw or "").split())
    if not text:return LocationPrecision.UNKNOWN
    if re.search(r"\b(near|nearby|around|vicinity of|approximately|approx\.?|outside)\b",text,re.I):return LocationPrecision.APPROXIMATE
    if re.search(r"\b(road|street|st\.?|avenue|ave\.?|highway|lane|cross|main road|no\.\s*\d+)\b",text,re.I):return LocationPrecision.STREET
    return LocationPrecision.CITY

def components(raw:str,metadata:dict|None=None)->dict:
    meta=metadata or {}; out={}
    for key in ("country","state","district","city","locality"):
        value=meta.get(key)
        if isinstance(value,str) and value.strip():out[key]=value.strip()[:300]
    return out

from pydantic import BaseModel,Field
from typing import Literal
from app.models.geospatial import ContradictionStatus
from app.models.geospatial import LocationPrecision
class GeocodeRequest(BaseModel):limit:int=Field(default=25,ge=1,le=100)
class ManualLocation(BaseModel):
    raw_text:str=Field(min_length=1,max_length=1000);precision:LocationPrecision=LocationPrecision.UNKNOWN;latitude:float|None=Field(default=None,ge=-90,le=90);longitude:float|None=Field(default=None,ge=-180,le=180);country:str|None=Field(default=None,max_length=200);state:str|None=Field(default=None,max_length=200);district:str|None=Field(default=None,max_length=200);city:str|None=Field(default=None,max_length=200);locality:str|None=Field(default=None,max_length=300)
class LocationRebuildRequest(BaseModel):
    include_evidence:bool=True;include_timeline:bool=True;include_historical:bool=True;include_sources:bool=True
class ContradictionReview(BaseModel):status:ContradictionStatus|None=None;priority:Literal["HIGH","MEDIUM","LOW"]|None=None;investigator_note:str|None=Field(default=None,max_length=5000)

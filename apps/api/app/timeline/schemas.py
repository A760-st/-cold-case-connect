from datetime import date
from uuid import UUID
from pydantic import BaseModel, Field, model_validator
from app.models.timeline import TimelineDatePrecision, TimelineEventType, TimelineImportance, TimelineSourceType, TimelineStatus

class GenerateTimeline(BaseModel):
    scope: str = Field(default="ALL", pattern="^(ALL|EVIDENCE|HISTORICAL|WEB|NEWS)$")
class ManualTimelineEvent(BaseModel):
    title: str = Field(min_length=1,max_length=500); description: str = Field(default="",max_length=10000)
    event_type: TimelineEventType = TimelineEventType.INVESTIGATOR_NOTE
    date_start: date|None=None; date_end: date|None=None; date_precision: TimelineDatePrecision=TimelineDatePrecision.UNKNOWN; date_text: str=Field(default="",max_length=500)
    location: str|None=Field(default=None,max_length=500); importance: TimelineImportance=TimelineImportance.MEDIUM
    @model_validator(mode="after")
    def check_range(self):
        if self.date_start and self.date_end and self.date_end < self.date_start: raise ValueError("date_end must not precede date_start")
        if self.date_precision == TimelineDatePrecision.UNKNOWN and (self.date_start or self.date_end): raise ValueError("UNKNOWN precision cannot include normalized dates")
        if self.date_precision != TimelineDatePrecision.UNKNOWN and not self.date_start: raise ValueError("a known precision requires date_start")
        if self.date_start and not self.date_end and self.date_precision in {TimelineDatePrecision.EXACT,TimelineDatePrecision.DAY}: self.date_end=self.date_start
        return self
class TimelineEventPatch(BaseModel):
    title: str|None=Field(default=None,min_length=1,max_length=500); description: str|None=Field(default=None,max_length=10000)
    event_type: TimelineEventType|None=None; date_start: date|None=None; date_end: date|None=None; date_precision: TimelineDatePrecision|None=None; date_text: str|None=Field(default=None,max_length=500)
    location: str|None=Field(default=None,max_length=500); importance: TimelineImportance|None=None; status: TimelineStatus|None=None
    @model_validator(mode="after")
    def check_range(self):
        if self.date_start and self.date_end and self.date_end < self.date_start: raise ValueError("date_end must not precede date_start")
        return self

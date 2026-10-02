from dataclasses import dataclass
from threading import Lock
from time import monotonic, sleep
import httpx
from app.config import settings

@dataclass
class GeocodeResult:
    status:str; provider:str; latitude:float|None=None;longitude:float|None=None;display_name:str|None=None;confidence:str="UNKNOWN";components:dict|None=None;raw:dict|None=None

class Geocoder:
    """Provider interface: return source coordinates and never guess from local strings."""
    def geocode_location(self,location_text:str)->GeocodeResult:
        raise NotImplementedError

class NominatimGeocoder(Geocoder):
    _lock=Lock();_last_call=0.0
    def geocode_location(self,location_text:str)->GeocodeResult:
        if not settings.geocoding_enabled:return GeocodeResult("NOT_ATTEMPTED","nominatim")
        with self._lock:
            interval=1/max(1,settings.geocoding_rate_limit);delay=interval-(monotonic()-self._last_call)
            if delay>0:sleep(delay)
            self._last_call=monotonic()
        try:
            response=httpx.get("https://nominatim.openstreetmap.org/search",params={"q":location_text,"format":"jsonv2","addressdetails":1,"limit":1},headers={"User-Agent":settings.geocoding_user_agent},timeout=settings.geocoding_timeout_seconds)
            response.raise_for_status();rows=response.json()
            if not rows:return GeocodeResult("NOT_FOUND","nominatim",raw={"query":location_text,"retrieved_at":monotonic()})
            item=rows[0];address=item.get("address") or {};kind=item.get("type") or item.get("addresstype") or ""
            return GeocodeResult("GEOCODED","nominatim",float(item["lat"]),float(item["lon"]),item.get("display_name"),"MEDIUM",{"country":address.get("country"),"state":address.get("state"),"district":address.get("state_district") or address.get("county"),"city":address.get("city") or address.get("town") or address.get("village"),"locality":address.get("suburb") or address.get("neighbourhood")}, {"query":location_text,"osm_type":item.get("osm_type"),"osm_id":item.get("osm_id"),"place_type":kind})
        except (httpx.HTTPError,ValueError,KeyError,TypeError):return GeocodeResult("FAILED","nominatim",raw={"query":location_text,"error":"geocoding unavailable"})

def get_geocoder()->Geocoder:
    provider=settings.geocoding_provider.casefold()
    if provider=="nominatim":return NominatimGeocoder()
    raise ValueError("Unsupported geocoding provider")

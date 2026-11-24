"""Live travel supplier integration, kept server-side and quote-only by default."""
from __future__ import annotations

import time
from typing import Any, Dict, List

import httpx

from app.config import get_settings


class TravelSupplierConfigurationError(RuntimeError):
    """Raised when a deployment has not supplied travel-provider credentials."""


class TravelSupplierError(RuntimeError):
    """Raised for a supplier error without leaking credentials to callers."""


_token: Dict[str, Any] = {"value": "", "expires_at": 0.0}


def _settings():
    return get_settings()


def _base_url() -> str:
    return str(_settings().AMADEUS_API_BASE_URL or "https://test.api.amadeus.com").rstrip("/")


async def _amadeus_token() -> str:
    settings = _settings()
    client_id = str(settings.AMADEUS_CLIENT_ID or "").strip()
    client_secret = str(settings.AMADEUS_CLIENT_SECRET or "").strip()
    if not client_id or not client_secret:
        raise TravelSupplierConfigurationError(
            "Live travel quotes need AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET in the service environment."
        )
    if _token["value"] and float(_token["expires_at"]) > time.monotonic() + 30:
        return str(_token["value"])
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post(
                f"{_base_url()}/v1/security/oauth2/token",
                data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        response.raise_for_status()
        payload = response.json() or {}
    except httpx.HTTPError as exc:
        raise TravelSupplierError("Amadeus authentication failed. Check the travel supplier configuration.") from exc
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise TravelSupplierError("Amadeus did not return an access token.")
    _token.update(value=token, expires_at=time.monotonic() + max(60, int(payload.get("expires_in") or 1800)))
    return token


def _flight_summary(offer: Dict[str, Any]) -> Dict[str, Any]:
    itineraries = list(offer.get("itineraries") or [])
    legs: List[Dict[str, Any]] = []
    for itinerary in itineraries:
        segments = list(itinerary.get("segments") or [])
        if not segments:
            continue
        first, last = segments[0], segments[-1]
        legs.append({
            "departure": (first.get("departure") or {}).get("at", ""),
            "arrival": (last.get("arrival") or {}).get("at", ""),
            "from": (first.get("departure") or {}).get("iataCode", ""),
            "to": (last.get("arrival") or {}).get("iataCode", ""),
            "stops": max(0, len(segments) - 1),
            "carriers": [str(segment.get("carrierCode") or "") for segment in segments if segment.get("carrierCode")],
        })
    price = offer.get("price") or {}
    validating = list(offer.get("validatingAirlineCodes") or [])
    return {
        "supplier_offer_id": str(offer.get("id") or ""),
        "total": str(price.get("grandTotal") or price.get("total") or ""),
        "currency": str(price.get("currency") or ""),
        "last_ticketing_date": str(offer.get("lastTicketingDate") or ""),
        "validating_airlines": validating,
        "legs": legs,
        # Keep the supplier offer server-side so pricing/ordering can use the
        # exact offer after finance selects it; do not expose credentials.
        "raw_offer": offer,
    }


async def search_amadeus_flights(
    *, origin_iata: str, destination_iata: str, departure_date: str,
    return_date: str = "", adults: int = 1, currency_code: str = "INR",
) -> List[Dict[str, Any]]:
    token = await _amadeus_token()
    params = {
        "originLocationCode": origin_iata.strip().upper(),
        "destinationLocationCode": destination_iata.strip().upper(),
        "departureDate": departure_date,
        "adults": max(1, min(int(adults), 9)),
        "currencyCode": currency_code.strip().upper() or "INR",
        "max": 8,
    }
    if return_date:
        params["returnDate"] = return_date
    try:
        async with httpx.AsyncClient(timeout=35) as client:
            response = await client.get(
                f"{_base_url()}/v2/shopping/flight-offers",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        response.raise_for_status()
        payload = response.json() or {}
    except httpx.HTTPError as exc:
        raise TravelSupplierError("Live flight search failed. Check route, travel dates, and supplier access.") from exc
    return [_flight_summary(offer) for offer in list(payload.get("data") or [])]

import logging

import httpx

logger = logging.getLogger(__name__)


async def fetch_fear_greed() -> dict:
    """Fetch crypto Fear & Greed Index from Alternative.me."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://api.alternative.me/fng/?limit=1")
            resp.raise_for_status()
            data = resp.json()

        entry = data["data"][0]
        return {
            "value": int(entry["value"]),
            "label": entry["value_classification"],
        }
    except Exception:
        logger.warning("Failed to fetch Fear & Greed index")
        return {"value": None, "label": None}

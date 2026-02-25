from __future__ import annotations

from typing import Any, Dict

import httpx
from app.mcp_server.server import mcp

# ── Config ────────────────────────────────────────────────────────────
# Primary: supports fiat + precious metals (XAU, XAG, etc.)
_CURRENCY_API = "https://latest.currency-api.pages.dev/v1/currencies/{base}.json"
_CURRENCY_API_FALLBACK = (
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{base}.json"
)
# Secondary (fiat-only fallback)
_FIAT_API = "https://open.er-api.com/v6/latest/{base}"

_HTTP_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

_ALIASES: Dict[str, str] = {
    # Precious metals
    "ONS": "XAU",
    "ALTIN": "XAU",
    "GOLD": "XAU",
    "GUMUS": "XAG",
    "SILVER": "XAG",
    "PLATINUM": "XPT",
    "PALLADIUM": "XPD",
    # Common local names
    "EURO": "EUR",
    "DOLAR": "USD",
    "DOLLAR": "USD",
    "STERLIN": "GBP",
    "POUND": "GBP",
    "YEN": "JPY",
    "FRANK": "CHF",
    "LIRA": "TRY",
    "RUBLE": "RUB",
    "RUPI": "INR",
    "RUPEE": "INR",
    "YUAN": "CNY",
    "WON": "KRW",
    "REAL": "BRL",
    "KRONA": "SEK",
}


def _resolve(code: str) -> str:
    key = code.strip().upper()
    return _ALIASES.get(key, key)


# ── Data Fetching ─────────────────────────────────────────────────────

async def _fetch_from_currency_api(client: httpx.AsyncClient, base: str) -> Dict[str, float] | None:
    """Fetch from fawazahmed0 currency-api (supports fiat + metals)."""
    base_lower = base.lower()
    for url_tpl in (_CURRENCY_API, _CURRENCY_API_FALLBACK):
        try:
            resp = await client.get(url_tpl.format(base=base_lower))
            if resp.status_code == 200:
                data = resp.json()
                rates = data.get(base_lower)
                if rates and isinstance(rates, dict):
                    return {k.upper(): float(v) for k, v in rates.items() if v}
        except Exception:
            continue
    return None


async def _fetch_from_fiat_api(client: httpx.AsyncClient, base: str) -> Dict[str, float] | None:
    """Fetch from open.er-api (fiat-only fallback)."""
    try:
        resp = await client.get(_FIAT_API.format(base=base.upper()))
        if resp.status_code == 200:
            data = resp.json()
            if data.get("result") == "success":
                return {k.upper(): float(v) for k, v in data.get("rates", {}).items()}
    except Exception:
        pass
    return None


async def _get_rate(base: str, quote: str) -> tuple[float, str]:
    """
    Get the conversion rate from base to quote.
    Tries currency-api first (fiat + metals), falls back to open.er-api (fiat only).
    Returns (rate, provider_name).
    """
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        # Try primary source (supports metals + fiat)
        rates = await _fetch_from_currency_api(client, base)
        if rates and quote in rates:
            return rates[quote], "currency-api"

        # Fallback: open.er-api (fiat only)
        rates = await _fetch_from_fiat_api(client, base)
        if rates and quote in rates:
            return rates[quote], "open.er-api"

        # Last resort: cross-rate via USD
        # Fetch both base/USD and quote/USD, then calculate cross-rate
        usd_rates = await _fetch_from_currency_api(client, "USD")
        if usd_rates and base in usd_rates and quote in usd_rates:
            rate = usd_rates[quote] / usd_rates[base]
            return rate, "currency-api (USD cross-rate)"

        raise ValueError(
            f"Could not find rate for {base} -> {quote}. "
            f"Please check if both currency codes are valid."
        )


# ── MCP Tool ──────────────────────────────────────────────────────────

@mcp.tool
async def fx_convert(base: str, quote: str, amount: float = 1.0) -> Dict[str, Any]:
    """
    Universal currency & precious metal converter.

    Supports 150+ fiat currencies (USD, EUR, TRY, GBP, JPY, CNY, ...)
    and precious metals (XAU/ONS, XAG, XPT, XPD).

    Args:
        base: Source currency code (e.g. "USD", "TRY", "ONS", "EUR", "GBP")
        quote: Target currency code (e.g. "TRY", "USD", "EUR", "ONS", "GBP")
        amount: Amount to convert (default: 1.0)

    Examples:
        fx_convert("USD", "TRY") -> 1 USD to TRY
        fx_convert("ONS", "USD") -> 1 ounce of gold in USD
        fx_convert("EUR", "TRY", 100) -> 100 EUR to TRY
        fx_convert("GBP", "USD", 50) -> 50 GBP to USD
    """
    base_code = _resolve(base)
    quote_code = _resolve(quote)

    if base_code == quote_code:
        return {
            "base": base.upper(),
            "quote": quote.upper(),
            "rate": 1.0,
            "amount": amount,
            "result": amount,
            "provider": "identity",
        }

    try:
        rate, provider = await _get_rate(base_code, quote_code)
        result_val = amount * rate

        return {
            "base": base.upper(),
            "quote": quote.upper(),
            "rate": round(rate, 6),
            "amount": amount,
            "result": round(result_val, 6),
            "provider": provider,
        }
    except Exception as e:
        return {
            "error": str(e),
            "status": "failed",
        }

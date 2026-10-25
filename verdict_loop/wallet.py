"""Read-only payer wallet balance checks (Base mainnet).

Used by the live-mode balance guard: before a pass signs anything, the
loop reads the payer's USDC balance straight from the Base chain
(`eth_call balanceOf` on the USDC contract) over public JSON-RPC
endpoints, trying each in order. No key material is involved — this is
a public read of a public address.

Returns None when no endpoint answers with a parseable result. The
caller decides what an unreadable balance means; the loop warns and
proceeds on the spend cap alone (an RPC outage must not brick the
agent), while a *known* balance below the planned spend is a hard
stop before anything is signed.
"""

from __future__ import annotations

import httpx

USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

BASE_RPC_URLS = (
    "https://mainnet.base.org",
    "https://base-rpc.publicnode.com",
    "https://base.llamarpc.com",
)

_BALANCE_OF_SELECTOR = "0x70a08231"  # ERC-20 balanceOf(address)


def usdc_balance_units(
    http: httpx.Client,
    address: str,
    *,
    rpc_urls: tuple[str, ...] = BASE_RPC_URLS,
) -> int | None:
    """USDC balance of `address` on Base, in base units (6 decimals).

    Tries each RPC in order; returns None if none answers parseably.
    """
    data = _BALANCE_OF_SELECTOR + address.removeprefix("0x").lower().rjust(64, "0")
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": USDC_BASE, "data": data}, "latest"],
    }
    for url in rpc_urls:
        try:
            response = http.post(url, json=body)
            payload = response.json()
        except Exception:
            continue
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, str) and result.startswith("0x"):
                try:
                    return int(result, 16)
                except ValueError:
                    continue
    return None

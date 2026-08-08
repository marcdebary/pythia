"""Kalshi REST + WebSocket API client.

Auth: RSA-private-key signed requests (Kalshi switched away from API-key-secret
in 2024). User provides KALSHI_PRIVATE_KEY_PATH + KALSHI_KEY_ID.

Free trial / demo env: api.demo.kalshi.co
Production:           api.elections.kalshi.com / trading-api.kalshi.com

Docs: https://docs.kalshi.com/
"""
import os
from urllib.parse import urlparse
import time
import base64
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as crypto_padding

logger = logging.getLogger(__name__)

_PROD = "https://api.elections.kalshi.com/trade-api/v2"
_DEMO = "https://demo-api.kalshi.co/trade-api/v2"


class KalshiError(Exception):
    pass


class KalshiClient:
    """Nur lesender Zugriff. Die Methoden zum Aufgeben und Stornieren von Orders
    sind bewusst entfernt.

    Pythia misst, ob ein Vorsprung existiert und ob er ausfuehrbar waere. Es
    handelt nicht. Ein Messinstrument, das nebenbei Orders absetzen kann, ist
    kein Messinstrument mehr - und jeder Fehler darin kostet echtes Geld statt
    einer falschen Zahl."""
    def __init__(self, key_id: Optional[str] = None,
                 private_key_path: Optional[str] = None,
                 demo: bool = False):
        self.key_id = key_id or os.environ.get("KALSHI_KEY_ID")
        self.demo = demo or os.environ.get("KALSHI_DEMO", "0") == "1"
        self.base = _DEMO if self.demo else _PROD
        self._private_key = None
        pk_path = private_key_path or os.environ.get("KALSHI_PRIVATE_KEY_PATH", "/data/kalshi_private.pem")
        self._pk_path = pk_path
        if self.key_id and Path(pk_path).exists():
            with open(pk_path, "rb") as f:
                self._private_key = serialization.load_pem_private_key(f.read(), password=None)
        self._client = httpx.Client(timeout=15.0)

    @property
    def is_authenticated(self) -> bool:
        return bool(self.key_id and self._private_key)

    def assert_authenticated(self) -> None:
        """Fuer alles Schreibende: lieber sofort scheitern als still 401 sammeln."""
        if self.is_authenticated:
            return
        missing = []
        if not self.key_id:
            missing.append("KALSHI_KEY_ID (leer oder nicht gesetzt)")
        if not self._private_key:
            missing.append(f"privater Schluessel unter {self._pk_path}")
        raise KalshiError(
            "Kalshi-Client ist nicht authentifiziert, fehlt: " + "; ".join(missing)
            + ". Lesende Endpunkte funktionieren ohne Signatur, schreibende nicht."
        )

    def _sign(self, method: str, path: str, timestamp_ms: int) -> str:
        """RSA-PSS signature over 'timestamp + method + path'."""
        message = f"{timestamp_ms}{method.upper()}{path}".encode()
        signature = self._private_key.sign(
            message,
            crypto_padding.PSS(
                mgf=crypto_padding.MGF1(hashes.SHA256()),
                salt_length=crypto_padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode()

    def _headers(self, method: str, path: str) -> Dict[str, str]:
        if not self.is_authenticated:
            return {}
        ts = int(time.time() * 1000)
        # Kalshi signiert den VOLLEN Pfad inkl. /trade-api/v2. Pythia signierte
        # nur den kurzen Pfad -> INCORRECT_API_KEY_SIGNATURE bei jedem privaten
        # Endpunkt. Belegt 2026-07-31: kurz -> 401, voll -> 200.
        sig = self._sign(method, urlparse(self.base).path + path, ts)
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": str(ts),
            "KALSHI-ACCESS-SIGNATURE": sig,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> Dict:
        url = f"{self.base}{path}"
        headers = self._headers(method, path)
        headers.update(kwargs.pop("headers", {}))
        r = self._client.request(method, url, headers=headers, **kwargs)
        if r.status_code >= 400:
            raise KalshiError(f"{method} {path} → {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    # ----- Public endpoints -----

    def list_events(self, status: str = "open", limit: int = 100,
                    cursor: Optional[str] = None) -> Dict:
        """List event groups (each event has multiple markets)."""
        params = {"status": status, "limit": min(limit, 200)}
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "/events", params=params)

    def list_markets(self, status: str = "open", limit: int = 100,
                     event_ticker: Optional[str] = None,
                     cursor: Optional[str] = None) -> Dict:
        params: Dict[str, Any] = {"status": status, "limit": min(limit, 1000)}
        if event_ticker:
            params["event_ticker"] = event_ticker
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "/markets", params=params)

    def list_series(self, category: Optional[str] = None,
                    limit: int = 200, cursor: Optional[str] = None) -> Dict:
        """List all series with optional category filter. Category names are
        capitalized in Kalshi (e.g. 'Economics', 'Financials', 'Crypto')."""
        params: Dict[str, Any] = {"limit": min(limit, 1000)}
        if category:
            params["category"] = category
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "/series", params=params)

    def list_events_by_series(self, series_ticker: str, status: str = "open",
                              limit: int = 200, cursor: Optional[str] = None) -> Dict:
        """List events under a specific series_ticker. status= param is accepted
        but ignored by Kalshi /events endpoint — kept for API parity."""
        params: Dict[str, Any] = {
            "series_ticker": series_ticker,
            "limit": min(limit, 200),
        }
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "/events", params=params)

    def get_market(self, ticker: str) -> Dict:
        return self._request("GET", f"/markets/{ticker}")

    def get_orderbook(self, ticker: str, depth: int = 10) -> Dict:
        return self._request("GET", f"/markets/{ticker}/orderbook", params={"depth": depth})

    # ----- Auth-required endpoints -----

    def get_balance(self) -> Dict:
        if not self.is_authenticated:
            raise KalshiError("Not authenticated")
        return self._request("GET", "/portfolio/balance")

    def get_positions(self) -> Dict:
        if not self.is_authenticated:
            raise KalshiError("Not authenticated")
        return self._request("GET", "/portfolio/positions")



    def get_order(self, order_id: str) -> Dict:
        """Fetch a single order by ID. Used by executor.confirm_kalshi_pending_fills."""
        if not self.is_authenticated:
            raise KalshiError("Not authenticated")
        return self._request("GET", f"/portfolio/orders/{order_id}")

    # ----- Normalization helpers -----

    @staticmethod
    def normalize_market(m: Dict) -> Optional[Dict]:
        """Convert Kalshi market dict → our internal format.

        Day 7 fix: Kalshi switched to dollar-string fields and many list-response
        markets have no bid/ask (only fetchable via orderbook). We skip
        provisional and multivariate parlay markets entirely. For traded markets
        we use last_price_dollars and liquidity_dollars as proxies.
        """
        # Skip provisional and parlay markets — they pollute the DB
        if m.get("is_provisional"):
            return None
        if (m.get("event_ticker") or "").startswith("KXMVE"):
            return None
        if (m.get("ticker") or "").startswith("KXMVE"):
            return None

        def _dollars(field):
            v = m.get(field)
            if v is None: return 0.0
            try: return float(v)
            except (ValueError, TypeError): return 0.0

        # Prefer bid/ask if present (cents), otherwise last_price_dollars
        yes_bid_d = m.get("yes_bid_dollars")
        yes_ask_d = m.get("yes_ask_dollars")
        yes_bid_c = m.get("yes_bid")
        yes_ask_c = m.get("yes_ask")
        if yes_bid_d is not None and yes_ask_d is not None:
            try:
                mid = (float(yes_bid_d) + float(yes_ask_d)) / 2.0
            except (ValueError, TypeError):
                mid = None
        elif yes_bid_c is not None and yes_ask_c is not None:
            mid = ((yes_bid_c + yes_ask_c) / 2) / 100.0
        else:
            last = _dollars("last_price_dollars")
            mid = last if last > 0 else None  # skip markets we can't price

        if mid is None:
            return None

        liquidity = _dollars("liquidity_dollars")
        # Kalshi /events nested markets expose volume as *_fp (fixed-point dollar
        # strings); the old *_dollars names are gone for volume. Prefer 24h, then
        # total, then legacy names, then liquidity as a last-resort proxy.
        volume_proxy = (_dollars("volume_24h_fp") or _dollars("volume_24h_dollars")
                        or _dollars("volume_fp") or _dollars("volume_dollars") or liquidity)

        close_at = None
        if m.get("close_time"):
            try:
                close_at = int(datetime.fromisoformat(
                    m["close_time"].replace("Z", "+00:00")
                ).replace(tzinfo=timezone.utc).timestamp())
            except Exception:
                pass
        # Range/ladder markets (CPI, index buckets) share ONE title and differ
        # only by yes_sub_title (the strike, e.g. "Exactly 4.3%"). Without it the
        # LLM/Grok score an underspecified question. Make each one self-contained.
        _title = m.get("title") or m.get("subtitle") or m.get("ticker") or ""
        _sub = (m.get("yes_sub_title") or "").strip()
        _question = ("%s (YES if: %s)" % (_title, _sub)
                     if (_sub and _sub.lower() not in _title.lower()) else _title)
        return {
            "venue": "kalshi",
            "external_id": m.get("ticker"),
            "question": _question,
            "category": (m.get("category") or "").lower() or None,
            "close_at": close_at,
            "yes_price": mid,
            "volume_24h": volume_proxy,
            "liquidity": liquidity,
            "status": "open" if m.get("status") == "active" else (m.get("status") or "open"),
        }

"""Market discovery module for finding BTC 15-minute Up/Down markets."""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

import config


@dataclass
class MarketInfo:
    """Information about a BTC Up/Down market."""
    condition_id: str
    question: str
    up_token_id: str
    down_token_id: str
    market_slug: str
    accepting_orders: bool = False
    end_date: Optional[str] = None


class MarketDiscovery:
    """Discovers and tracks BTC 15-minute Up/Down markets on Polymarket."""

    GAMMA_API_URL = "https://gamma-api.polymarket.com"

    def __init__(self):
        self.active_markets: dict[str, MarketInfo] = {}
        self.http_client = httpx.Client(timeout=30)

    def get_current_15m_timestamps(self) -> list[int]:
        """Get timestamp for the CURRENT 15-minute window only."""
        now = datetime.now(timezone.utc)

        # Round down to current 15-minute interval
        minutes = now.minute
        interval_start = (minutes // 15) * 15
        current_interval = now.replace(minute=interval_start, second=0, microsecond=0)
        current_ts = int(current_interval.timestamp())

        # Only return current interval - focus on ONE market at a time
        return [current_ts]

    def fetch_market_by_slug(self, slug: str) -> Optional[dict]:
        """Fetch a market event by its slug from the Gamma API."""
        try:
            url = f"{self.GAMMA_API_URL}/events/slug/{slug}"
            response = self.http_client.get(url)
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass  # Silently ignore - market might not exist yet
        return None

    def extract_token_ids(self, market: dict) -> tuple[Optional[str], Optional[str]]:
        """Extract Up and Down token IDs from market data."""
        import json

        up_token_id = None
        down_token_id = None

        clob_tokens_raw = market.get("clobTokenIds", [])
        outcomes_raw = market.get("outcomes", [])

        # Parse JSON strings if needed
        if isinstance(clob_tokens_raw, str):
            clob_tokens = json.loads(clob_tokens_raw)
        else:
            clob_tokens = clob_tokens_raw

        if isinstance(outcomes_raw, str):
            outcomes = json.loads(outcomes_raw)
        else:
            outcomes = outcomes_raw

        if len(clob_tokens) >= 2 and len(outcomes) >= 2:
            for i, outcome in enumerate(outcomes):
                if outcome.lower() == "up":
                    up_token_id = clob_tokens[i]
                elif outcome.lower() == "down":
                    down_token_id = clob_tokens[i]

        return up_token_id, down_token_id

    def discover_markets(self) -> list[MarketInfo]:
        """Discover all active BTC 15-minute Up/Down markets."""
        discovered = []
        timestamps = self.get_current_15m_timestamps()

        for ts in timestamps:
            slug = f"btc-updown-15m-{ts}"
            event = self.fetch_market_by_slug(slug)

            if not event:
                continue

            markets = event.get("markets", [])
            if not markets:
                continue

            market = markets[0]  # Each event has one market
            condition_id = market.get("conditionId", "")
            if not condition_id:
                continue

            # Skip already tracked markets
            if condition_id in self.active_markets:
                # Update accepting_orders status
                self.active_markets[condition_id].accepting_orders = market.get("acceptingOrders", False)
                continue

            up_token_id, down_token_id = self.extract_token_ids(market)
            if not up_token_id or not down_token_id:
                continue

            accepting_orders = market.get("acceptingOrders", False)

            market_info = MarketInfo(
                condition_id=condition_id,
                question=market.get("question", f"BTC Up or Down {ts}"),
                up_token_id=up_token_id,
                down_token_id=down_token_id,
                market_slug=slug,
                accepting_orders=accepting_orders,
                end_date=event.get("endDate")
            )

            discovered.append(market_info)
            self.active_markets[condition_id] = market_info

            if accepting_orders:
                print(f"  Found ACTIVE market: {market_info.question}")
            else:
                print(f"  Found market (closed): {market_info.question}")

        # Remove old/resolved markets
        self._cleanup_old_markets()

        return discovered

    def _cleanup_old_markets(self):
        """Remove markets that are no longer the current interval."""
        current_timestamps = set(self.get_current_15m_timestamps())
        to_remove = []

        for condition_id, market in self.active_markets.items():
            # Extract timestamp from slug
            try:
                ts_str = market.market_slug.split("-")[-1]
                ts = int(ts_str)
                # Remove if not in current timestamp list
                if ts not in current_timestamps:
                    to_remove.append(condition_id)
            except (ValueError, IndexError):
                pass

        for condition_id in to_remove:
            del self.active_markets[condition_id]

    def get_active_markets(self) -> list[MarketInfo]:
        """Get only markets that are currently accepting orders."""
        return [m for m in self.active_markets.values() if m.accepting_orders]

    def get_all_token_ids(self) -> list[str]:
        """Get all token IDs that should be subscribed to."""
        token_ids = []
        for market in self.active_markets.values():
            token_ids.append(market.up_token_id)
            token_ids.append(market.down_token_id)
        return token_ids

    def get_market_by_token_id(self, token_id: str) -> Optional[MarketInfo]:
        """Find the market that contains a given token ID."""
        for market in self.active_markets.values():
            if token_id in (market.up_token_id, market.down_token_id):
                return market
        return None

    def is_up_token(self, market: MarketInfo, token_id: str) -> bool:
        """Check if the token ID is the Up/Yes outcome."""
        return token_id == market.up_token_id

    def refresh_market_status(self):
        """Refresh the accepting_orders status for all tracked markets."""
        for condition_id, market_info in list(self.active_markets.items()):
            event = self.fetch_market_by_slug(market_info.market_slug)
            if event and event.get("markets"):
                market = event["markets"][0]
                market_info.accepting_orders = market.get("acceptingOrders", False)

    def close(self):
        """Close the HTTP client."""
        self.http_client.close()

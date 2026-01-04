"""Price monitoring and alerting module."""

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import config
from market_discovery import MarketDiscovery, MarketInfo


@dataclass
class MarketPrices:
    """Price state for a single market."""
    market_info: MarketInfo
    up_best_ask: Optional[float] = None
    down_best_ask: Optional[float] = None
    up_last_trade: Optional[float] = None
    down_last_trade: Optional[float] = None
    last_update: Optional[datetime] = None

    @property
    def up_price(self) -> Optional[float]:
        """Get the best available Up price."""
        return self.up_best_ask or self.up_last_trade

    @property
    def down_price(self) -> Optional[float]:
        """Get the best available Down price."""
        return self.down_best_ask or self.down_last_trade

    @property
    def sum_price(self) -> Optional[float]:
        """Calculate sum of Up and Down prices."""
        if self.up_price is not None and self.down_price is not None:
            return self.up_price + self.down_price
        return None

    @property
    def short_name(self) -> str:
        """Generate a short market identifier."""
        q = self.market_info.question
        if ":" in q:
            time_part = q.split(":")[-1][:5] if ":" in q else ""
            return f"BTC-15M-{time_part.replace(':', '').strip()}"
        return f"BTC-15M-{self.market_info.condition_id[:8]}"


class PriceMonitor:
    """Monitors prices and triggers alerts."""

    def __init__(self, market_discovery: MarketDiscovery, on_price_update=None):
        """
        Initialize price monitor.

        Args:
            market_discovery: Market discovery instance
            on_price_update: Optional callback called on each price update.
                            Signature: (market_id, market_name, up_price, down_price, sum_price)
        """
        self.market_discovery = market_discovery
        self.prices: dict[str, MarketPrices] = {}
        self.on_price_update = on_price_update

    def initialize_markets(self):
        """Initialize price tracking for all discovered markets."""
        for condition_id, market_info in self.market_discovery.active_markets.items():
            if condition_id not in self.prices:
                self.prices[condition_id] = MarketPrices(market_info=market_info)

    def process_message(self, message: dict):
        """Process incoming WebSocket message."""
        event_type = message.get("event_type", "")

        if event_type == "book":
            self._process_book(message)
        elif event_type == "price_change":
            self._process_price_change(message)
        elif event_type == "last_trade_price":
            self._process_last_trade(message)

    def _process_book(self, message: dict):
        """Process orderbook update message."""
        asset_id = message.get("asset_id", "")
        market_info = self.market_discovery.get_market_by_token_id(asset_id)
        if not market_info:
            return

        condition_id = market_info.condition_id
        if condition_id not in self.prices:
            self.prices[condition_id] = MarketPrices(market_info=market_info)

        prices = self.prices[condition_id]
        asks = message.get("asks", [])

        best_ask = None
        if asks:
            try:
                best_ask = min(float(a["price"]) for a in asks)
            except (KeyError, ValueError):
                pass

        if best_ask is not None:
            is_up = self.market_discovery.is_up_token(market_info, asset_id)
            if is_up:
                prices.up_best_ask = best_ask
            else:
                prices.down_best_ask = best_ask

            prices.last_update = datetime.now(timezone.utc)
            self._log_and_check_alert(prices)

    def _process_price_change(self, message: dict):
        """Process price change message."""
        changes = message.get("price_changes", [])
        for change in changes:
            asset_id = change.get("asset_id", "")
            market_info = self.market_discovery.get_market_by_token_id(asset_id)
            if not market_info:
                continue

            condition_id = market_info.condition_id
            if condition_id not in self.prices:
                self.prices[condition_id] = MarketPrices(market_info=market_info)

            prices = self.prices[condition_id]
            best_ask = change.get("best_ask")

            if best_ask is not None:
                try:
                    best_ask = float(best_ask)
                    is_up = self.market_discovery.is_up_token(market_info, asset_id)
                    if is_up:
                        prices.up_best_ask = best_ask
                    else:
                        prices.down_best_ask = best_ask

                    prices.last_update = datetime.now(timezone.utc)
                    self._log_and_check_alert(prices)
                except ValueError:
                    pass

    def _process_last_trade(self, message: dict):
        """Process last trade price message."""
        asset_id = message.get("asset_id", "")
        market_info = self.market_discovery.get_market_by_token_id(asset_id)
        if not market_info:
            return

        condition_id = market_info.condition_id
        if condition_id not in self.prices:
            self.prices[condition_id] = MarketPrices(market_info=market_info)

        prices = self.prices[condition_id]
        price = message.get("price")

        if price is not None:
            try:
                price = float(price)
                is_up = self.market_discovery.is_up_token(market_info, asset_id)
                if is_up:
                    prices.up_last_trade = price
                else:
                    prices.down_last_trade = price

                prices.last_update = datetime.now(timezone.utc)
                self._log_and_check_alert(prices)
            except ValueError:
                pass

    def _log_and_check_alert(self, prices: MarketPrices):
        """Log current prices and check for alert condition."""
        sum_price = prices.sum_price
        if sum_price is None:
            return

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        up_str = f"{prices.up_price:.4f}" if prices.up_price else "-.----"
        down_str = f"{prices.down_price:.4f}" if prices.down_price else "-.----"
        sum_str = f"{sum_price:.4f}"

        # Alert sound only (TUI handles display)
        if sum_price < config.ALERT_THRESHOLD:
            self._play_alert_sound()

        # Call trading callback if provided
        if self.on_price_update and prices.up_price and prices.down_price:
            self.on_price_update(
                market_id=prices.market_info.condition_id,
                market_name=prices.short_name,
                up_price=prices.up_price,
                down_price=prices.down_price,
                sum_price=sum_price,
            )

    def _play_alert_sound(self):
        """Play alert sound on macOS."""
        try:
            os.system('afplay /System/Library/Sounds/Glass.aiff &')
        except Exception:
            print("\a", end="")
            sys.stdout.flush()

#!/usr/bin/env python3
"""
Polymarket BTC 15-Minute Trading Bot (Gabagool Strategy)

Implements asymmetric hedging: buy YES when cheap, buy NO when cheap,
keeping avg_YES + avg_NO < 1.00 for guaranteed profit regardless of outcome.
"""

import signal
import time
from datetime import datetime, timezone

import config
from market_discovery import MarketDiscovery
from order_executor import create_executor
from position_tracker import PositionTracker
from price_monitor import PriceMonitor
from risk_manager import RiskManager
from trading_strategy import GabagoolStrategy
from tui import TradingTUI
from websocket_client import PolymarketWebSocket


class TradingBot:
    """Main trading bot implementing the Gabagool strategy."""

    def __init__(self):
        self.running = True

        # Core components
        self.market_discovery = MarketDiscovery()
        self.position_tracker = PositionTracker()

        # Strategy and risk
        self.strategy = GabagoolStrategy(
            min_shares_per_order=config.MIN_SHARES_PER_ORDER,
            max_shares_per_order=config.MAX_SHARES_PER_ORDER,
        )

        self.risk_manager = RiskManager(
            max_total_exposure=config.MAX_TOTAL_EXPOSURE,
            max_per_market=config.MAX_PER_MARKET_EXPOSURE,
            stop_trading_minutes_before_close=config.STOP_TRADING_BEFORE_CLOSE_MINUTES,
            max_unhedged_markets=config.MAX_UNHEDGED_MARKETS,
        )

        # Order execution
        self.executor = create_executor(
            mode=config.TRADING_MODE,
            initial_balance=config.PAPER_TRADING_BALANCE,
            api_key=config.API_KEY,
            api_secret=config.API_SECRET,
            passphrase=config.API_PASSPHRASE,
            private_key=config.PRIVATE_KEY,
        )

        # Price monitoring with trading callback
        self.price_monitor = PriceMonitor(
            self.market_discovery,
            on_price_update=self.on_price_update,
        )

        self.websocket: PolymarketWebSocket = None

        # TUI
        self.tui = TradingTUI(
            position_tracker=self.position_tracker,
            executor=self.executor,
            max_exposure=config.MAX_TOTAL_EXPOSURE,
        )

        # Stats
        self.trades_executed = 0

    def signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        self.running = False
        if self.websocket:
            self.websocket.stop()
        self.tui.stop()
        self.tui.print_final_summary()

    def _get_minutes_remaining(self, end_date: str) -> float:
        """Calculate minutes remaining until market close."""
        if not end_date:
            return 15.0  # Default to 15 minutes if unknown

        try:
            # Parse ISO format
            if end_date.endswith("Z"):
                end_time = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            else:
                end_time = datetime.fromisoformat(end_date)

            now = datetime.now(timezone.utc)
            remaining = (end_time - now).total_seconds() / 60
            return max(0, remaining)
        except (ValueError, TypeError):
            return 15.0  # Default if parsing fails

    def on_price_update(
        self,
        market_id: str,
        market_name: str,
        up_price: float,
        down_price: float,
        sum_price: float,
    ):
        """
        Called when prices update. Evaluate trading opportunities.

        Args:
            market_id: The market condition ID
            market_name: Human-readable market name
            up_price: Current UP/YES best ask price
            down_price: Current DOWN/NO best ask price
            sum_price: up_price + down_price
        """
        # Skip if prices are invalid
        if up_price <= 0 or down_price <= 0:
            return

        # Update TUI with latest prices
        self.tui.update_price(market_id, market_name, up_price, down_price, sum_price)

        # Get market info for token IDs and end time
        market_info = None
        for m in self.market_discovery.active_markets.values():
            if m.condition_id == market_id:
                market_info = m
                break

        if not market_info:
            return

        # Only trade markets that are accepting orders
        if not market_info.accepting_orders:
            return

        # Calculate minutes remaining until market close
        minutes_remaining = self._get_minutes_remaining(market_info.end_date)

        # Get or create position
        position = self.position_tracker.get_position(market_id, market_name)

        # Evaluate strategy with time awareness
        signal = self.strategy.evaluate(position, up_price, down_price, minutes_remaining)

        if signal:
            # Determine token ID
            if signal.side == "YES":
                token_id = market_info.up_token_id
            else:
                token_id = market_info.down_token_id

            # Risk check
            risk_result = self.risk_manager.can_trade(
                position=position,
                side=signal.side,
                price=signal.price,
                size=signal.quantity,
                position_tracker=self.position_tracker,
                market_end_time=market_info.end_date,
            )

            if risk_result.allowed:
                # Execute trade
                order_result = self.executor.buy_shares(
                    token_id=token_id,
                    side=signal.side,
                    price=signal.price,
                    size=signal.quantity,
                    market_name=market_name,
                )

                if order_result.status == "FILLED":
                    # Record in position tracker
                    self.position_tracker.record_buy(
                        market_id=market_id,
                        side=signal.side,
                        price=signal.price,
                        qty=signal.quantity,
                        market_name=market_name,
                    )
                    self.trades_executed += 1

                    # Log trade to TUI with urgency level
                    self.tui.log_trade(signal.side, signal.quantity, signal.price, market_name, signal.urgency)
            else:
                # Log why trade was blocked (for debugging)
                self.tui.log_activity(f"[dim]Blocked: {risk_result.reason[:40]}[/]")

        # Update TUI display
        self.tui.update()

    def discover_and_subscribe(self):
        """Discover markets and set up WebSocket subscriptions."""
        markets = self.market_discovery.discover_markets()

        if not markets:
            return False

        self.price_monitor.initialize_markets()
        token_ids = self.market_discovery.get_all_token_ids()

        if self.websocket:
            self.websocket.update_subscriptions(token_ids)
        else:
            self.websocket = PolymarketWebSocket(self.price_monitor.process_message)
            self.websocket.connect(token_ids)

        return True

    def run(self):
        """Main run loop."""
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        # Discover markets first (before TUI starts)
        self.discover_and_subscribe()

        # Start TUI
        self.tui.start()
        self.tui.log_activity(f"[cyan]Mode: {'PAPER' if config.TRADING_MODE == 'paper' else 'LIVE'}[/]")
        self.tui.log_activity(f"[dim]Max Exposure: ${config.MAX_TOTAL_EXPOSURE:.0f}[/]")

        last_refresh = time.time()

        while self.running:
            try:
                # Refresh markets periodically
                if time.time() - last_refresh > config.MARKET_REFRESH_INTERVAL:
                    self.tui.log_activity("[yellow]Refreshing markets...[/]")
                    self.discover_and_subscribe()
                    last_refresh = time.time()

                # Update TUI
                self.tui.update()
                time.sleep(0.25)  # 4 Hz update rate

            except KeyboardInterrupt:
                break
            except Exception as e:
                self.tui.log_activity(f"[red]Error: {e}[/]")
                time.sleep(5)


def main():
    """Entry point."""
    bot = TradingBot()
    bot.run()


if __name__ == "__main__":
    main()

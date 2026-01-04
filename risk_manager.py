"""Risk management for the trading bot."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from position_tracker import MarketPosition, PositionTracker


@dataclass
class RiskCheckResult:
    """Result of a risk check."""
    allowed: bool
    reason: str
    max_size: Optional[float] = None  # Max allowed size if partially allowed


class RiskManager:
    """
    Controls trading exposure and prevents excessive risk.

    Enforces limits on:
    - Total exposure across all markets
    - Exposure per individual market
    - Minimum profit margin requirements
    - Position imbalance limits
    """

    def __init__(
        self,
        max_total_exposure: float = 100.0,
        max_per_market: float = 50.0,
        min_profit_margin: float = 0.02,
        max_imbalance: float = 0.20,
        stop_trading_minutes_before_close: int = 2,
        max_unhedged_markets: int = 1,
    ):
        """
        Initialize risk manager.

        Args:
            max_total_exposure: Maximum total $ across all markets
            max_per_market: Maximum $ per single market
            min_profit_margin: Minimum required profit margin (1 - pair_cost)
            max_imbalance: Maximum allowed imbalance between YES and NO
            stop_trading_minutes_before_close: Stop trading N minutes before market closes
            max_unhedged_markets: Max markets with one-sided positions (complete hedge before new)
        """
        self.max_total_exposure = max_total_exposure
        self.max_per_market = max_per_market
        self.min_profit_margin = min_profit_margin
        self.max_imbalance = max_imbalance
        self.stop_trading_minutes_before_close = stop_trading_minutes_before_close
        self.max_unhedged_markets = max_unhedged_markets

        # Tracking
        self.trades_blocked = 0
        self.trades_allowed = 0

    def can_trade(
        self,
        position: MarketPosition,
        side: str,
        price: float,
        size: float,
        position_tracker: PositionTracker,
        market_end_time: Optional[str] = None,
    ) -> RiskCheckResult:
        """
        Check if a proposed trade is within risk limits.

        Args:
            position: Current position for the market
            side: "YES" or "NO"
            price: Proposed price
            size: Proposed quantity
            position_tracker: Tracker with all positions (for total exposure)
            market_end_time: ISO timestamp when market closes (optional)

        Returns:
            RiskCheckResult indicating if trade is allowed
        """
        trade_cost = price * size

        # Check 1: Market timing (don't trade too close to resolution)
        if market_end_time:
            time_check = self._check_market_timing(market_end_time)
            if not time_check.allowed:
                self.trades_blocked += 1
                return time_check

        # Check 2: Per-market exposure limit
        market_check = self._check_market_exposure(position, trade_cost)
        if not market_check.allowed:
            self.trades_blocked += 1
            return market_check

        # Check 3: Total exposure limit
        total_check = self._check_total_exposure(position_tracker, trade_cost)
        if not total_check.allowed:
            self.trades_blocked += 1
            return total_check

        # Check 4: Profit margin (simulated)
        margin_check = self._check_profit_margin(position, side, price, size)
        if not margin_check.allowed:
            self.trades_blocked += 1
            return margin_check

        # Check 5: Position imbalance
        balance_check = self._check_imbalance(position, side, size)
        if not balance_check.allowed:
            self.trades_blocked += 1
            return balance_check

        # Check 6: Unhedged markets limit
        unhedged_check = self._check_unhedged_markets(position, position_tracker)
        if not unhedged_check.allowed:
            self.trades_blocked += 1
            return unhedged_check

        self.trades_allowed += 1
        return RiskCheckResult(
            allowed=True,
            reason="All risk checks passed",
        )

    def _check_market_timing(self, market_end_time: str) -> RiskCheckResult:
        """Check if we're too close to market close."""
        try:
            # Parse ISO format
            if market_end_time.endswith("Z"):
                end_time = datetime.fromisoformat(market_end_time.replace("Z", "+00:00"))
            else:
                end_time = datetime.fromisoformat(market_end_time)

            now = datetime.now(timezone.utc)
            minutes_remaining = (end_time - now).total_seconds() / 60

            if minutes_remaining < self.stop_trading_minutes_before_close:
                return RiskCheckResult(
                    allowed=False,
                    reason=f"Market closes in {minutes_remaining:.1f} minutes "
                           f"(min: {self.stop_trading_minutes_before_close})",
                )
        except (ValueError, TypeError):
            # If we can't parse the time, allow trading
            pass

        return RiskCheckResult(allowed=True, reason="Market timing OK")

    def _check_market_exposure(
        self,
        position: MarketPosition,
        trade_cost: float,
    ) -> RiskCheckResult:
        """Check per-market exposure limit."""
        current_exposure = position.total_cost
        new_exposure = current_exposure + trade_cost

        if new_exposure > self.max_per_market:
            remaining = self.max_per_market - current_exposure
            if remaining > 0:
                return RiskCheckResult(
                    allowed=False,
                    reason=f"Would exceed per-market limit: ${new_exposure:.2f} > ${self.max_per_market:.2f}",
                    max_size=remaining / (trade_cost / (trade_cost / remaining)) if trade_cost > 0 else 0,
                )
            return RiskCheckResult(
                allowed=False,
                reason=f"Per-market limit reached: ${current_exposure:.2f} >= ${self.max_per_market:.2f}",
            )

        return RiskCheckResult(allowed=True, reason="Market exposure OK")

    def _check_total_exposure(
        self,
        position_tracker: PositionTracker,
        trade_cost: float,
    ) -> RiskCheckResult:
        """Check total exposure across all markets."""
        current_total = position_tracker.total_exposure()
        new_total = current_total + trade_cost

        if new_total > self.max_total_exposure:
            remaining = self.max_total_exposure - current_total
            if remaining > 0:
                return RiskCheckResult(
                    allowed=False,
                    reason=f"Would exceed total limit: ${new_total:.2f} > ${self.max_total_exposure:.2f}",
                    max_size=remaining,
                )
            return RiskCheckResult(
                allowed=False,
                reason=f"Total limit reached: ${current_total:.2f} >= ${self.max_total_exposure:.2f}",
            )

        return RiskCheckResult(allowed=True, reason="Total exposure OK")

    def _check_profit_margin(
        self,
        position: MarketPosition,
        side: str,
        price: float,
        size: float,
    ) -> RiskCheckResult:
        """Check if trade would maintain acceptable profit margin."""
        # Get current values
        our_qty = position.qty_yes if side == "YES" else position.qty_no
        our_cost = position.cost_yes if side == "YES" else position.cost_no
        other_avg = position.avg_no if side == "YES" else position.avg_yes

        # Calculate new average after trade
        new_cost = our_cost + price * size
        new_qty = our_qty + size
        new_avg = new_cost / new_qty if new_qty > 0 else price

        # If we don't have the other side yet, we can't check pair cost
        if other_avg == 0:
            return RiskCheckResult(allowed=True, reason="No hedge yet - margin check skipped")

        # Calculate new pair cost
        new_pair_cost = new_avg + other_avg
        new_margin = 1.0 - new_pair_cost

        if new_margin < self.min_profit_margin:
            return RiskCheckResult(
                allowed=False,
                reason=f"Profit margin too low: {new_margin:.4f} < {self.min_profit_margin:.4f} "
                       f"(pair_cost would be {new_pair_cost:.4f})",
            )

        return RiskCheckResult(allowed=True, reason="Profit margin OK")

    def _check_imbalance(
        self,
        position: MarketPosition,
        side: str,
        size: float,
    ) -> RiskCheckResult:
        """Check if trade would create too much position imbalance."""
        our_qty = position.qty_yes if side == "YES" else position.qty_no
        other_qty = position.qty_no if side == "YES" else position.qty_yes

        # If no position on other side yet, allow some buildup
        if other_qty == 0:
            # Allow building first side, but not too much
            max_unhedged = 100  # Max shares on one side without hedge
            if our_qty + size > max_unhedged:
                return RiskCheckResult(
                    allowed=False,
                    reason=f"Too much unhedged exposure: {our_qty + size:.1f} > {max_unhedged}",
                    max_size=max(0, max_unhedged - our_qty),
                )
            return RiskCheckResult(allowed=True, reason="Unhedged buildup allowed")

        # Calculate imbalance after trade
        new_our_qty = our_qty + size
        total = new_our_qty + other_qty
        if total > 0:
            imbalance = abs(new_our_qty - other_qty) / (total / 2)

            if imbalance > self.max_imbalance:
                return RiskCheckResult(
                    allowed=False,
                    reason=f"Would create imbalance: {imbalance:.2%} > {self.max_imbalance:.2%}",
                )

        return RiskCheckResult(allowed=True, reason="Balance OK")

    def _check_unhedged_markets(
        self,
        position: MarketPosition,
        position_tracker: PositionTracker,
    ) -> RiskCheckResult:
        """
        Prevent opening new positions if too many markets are unhedged.

        Forces completing hedges before spreading capital across markets.
        """
        # If this position already has exposure, allow trading (completing hedge or adding)
        if position.qty_yes > 0 or position.qty_no > 0:
            return RiskCheckResult(allowed=True, reason="Adding to existing position")

        # Count how many markets have unhedged (one-sided) positions
        unhedged_count = 0
        for pos in position_tracker.positions.values():
            if pos.market_id == position.market_id:
                continue  # Skip current market
            # Unhedged = has position on one side but not both
            has_yes = pos.qty_yes > 0
            has_no = pos.qty_no > 0
            if (has_yes or has_no) and not (has_yes and has_no):
                unhedged_count += 1

        if unhedged_count >= self.max_unhedged_markets:
            return RiskCheckResult(
                allowed=False,
                reason=f"Already have {unhedged_count} unhedged market(s) - complete hedge first",
            )

        return RiskCheckResult(allowed=True, reason="Unhedged limit OK")

    def get_max_trade_size(
        self,
        position: MarketPosition,
        side: str,
        price: float,
        position_tracker: PositionTracker,
    ) -> float:
        """
        Calculate maximum allowed trade size given all constraints.

        Args:
            position: Current market position
            side: "YES" or "NO"
            price: Price per share
            position_tracker: Tracker with all positions

        Returns:
            Maximum shares that can be bought
        """
        if price <= 0:
            return 0

        # Start with a large number and constrain
        max_size = 1000.0

        # Per-market constraint
        remaining_market = self.max_per_market - position.total_cost
        if remaining_market <= 0:
            return 0
        max_size = min(max_size, remaining_market / price)

        # Total exposure constraint
        remaining_total = self.max_total_exposure - position_tracker.total_exposure()
        if remaining_total <= 0:
            return 0
        max_size = min(max_size, remaining_total / price)

        # Balance constraint
        our_qty = position.qty_yes if side == "YES" else position.qty_no
        other_qty = position.qty_no if side == "YES" else position.qty_yes

        if other_qty > 0:
            # Keep within balance tolerance
            max_for_balance = other_qty * (1 + self.max_imbalance) - our_qty
            max_size = min(max_size, max(0, max_for_balance))

        return max(0, max_size)

    def summary(self) -> str:
        """Get summary of risk manager activity."""
        total = self.trades_allowed + self.trades_blocked
        if total == 0:
            return "Risk Manager: No trades evaluated yet"

        block_rate = (self.trades_blocked / total) * 100

        return (
            f"Risk Manager Summary:\n"
            f"  Trades Allowed: {self.trades_allowed}\n"
            f"  Trades Blocked: {self.trades_blocked}\n"
            f"  Block Rate: {block_rate:.1f}%\n"
            f"  Limits: ${self.max_total_exposure:.0f} total, "
            f"${self.max_per_market:.0f}/market"
        )

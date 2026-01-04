"""
Gabagool Strategy: Skew-based inventory rebalancing with loss-bounded hedging.

Key principles:
1. Enter when market is skewed (one side very cheap, other expensive)
2. Buy cheap side first (13-20¢ range)
3. Hedge with expensive side (up to 85¢) to cap risk
4. Accept pair_cost near 1.0 (loss-bounded, not guaranteed profit)
"""

from dataclasses import dataclass
from typing import Optional, Tuple

import config
from position_tracker import MarketPosition


@dataclass
class TradeSignal:
    """Signal to execute a trade."""
    side: str  # "YES" or "NO"
    price: float
    quantity: float
    reason: str
    urgency: str = "normal"  # normal, eager, urgent, emergency


class GabagoolStrategy:
    """
    Skew-based inventory rebalancing strategy.

    Entry: When |UP - DOWN| > 0.60 and min(UP, DOWN) < 0.20
    Hedge: Buy other side up to 0.85 if it reduces unhedged exposure
    Goal: Keep pair_cost <= urgency threshold (0.995 to 1.02)
    """

    def __init__(
        self,
        min_shares_per_order: float = 5.0,
        max_shares_per_order: float = 50.0,
    ):
        self.min_shares_per_order = min_shares_per_order
        self.max_shares_per_order = max_shares_per_order

    def _get_urgency_level(self, minutes_remaining: float) -> str:
        """Determine trading urgency based on time to market close."""
        if minutes_remaining > config.URGENCY_THRESHOLDS["normal"]["minutes"]:
            return "normal"
        elif minutes_remaining > config.URGENCY_THRESHOLDS["eager"]["minutes"]:
            return "eager"
        elif minutes_remaining > config.URGENCY_THRESHOLDS["urgent"]["minutes"]:
            return "urgent"
        else:
            return "emergency"

    def _get_max_pair_cost(self, urgency: str) -> float:
        """Get maximum acceptable pair_cost for urgency level."""
        return config.URGENCY_THRESHOLDS.get(
            urgency, config.URGENCY_THRESHOLDS["normal"]
        )["max_pair_cost"]

    def _simulate_pair_cost(
        self,
        position: MarketPosition,
        side: str,
        price: float,
        qty: float,
    ) -> float:
        """Simulate what pair_cost would be after a buy."""
        if side == "YES":
            new_cost_yes = position.cost_yes + price * qty
            new_qty_yes = position.qty_yes + qty
            new_avg_yes = new_cost_yes / new_qty_yes if new_qty_yes > 0 else price
            new_avg_no = position.avg_no
        else:
            new_cost_no = position.cost_no + price * qty
            new_qty_no = position.qty_no + qty
            new_avg_no = new_cost_no / new_qty_no if new_qty_no > 0 else price
            new_avg_yes = position.avg_yes

        # If one side has no position, can't calculate pair cost yet
        if new_avg_yes == 0 or new_avg_no == 0:
            return price  # Return just this side's price as estimate

        return new_avg_yes + new_avg_no

    def evaluate(
        self,
        position: MarketPosition,
        up_price: float,
        down_price: float,
        minutes_remaining: float = 15.0,
    ) -> Optional[TradeSignal]:
        """
        Evaluate current prices and position to determine if we should trade.

        Logic:
        1. No position: Enter if skew > 0.60 and cheap side < 0.20
        2. One side: Hedge if simulated pair_cost <= max for urgency
        3. Both sides: Add more if it improves pair_cost
        """
        has_yes = position.qty_yes > 0
        has_no = position.qty_no > 0
        urgency = self._get_urgency_level(minutes_remaining)

        # CASE 1: No position yet - check for skew-based entry
        if not has_yes and not has_no:
            return self._evaluate_first_leg(up_price, down_price, minutes_remaining)

        # CASE 2: Have one side only - complete the hedge
        if has_yes and not has_no:
            return self._evaluate_completing_hedge(
                position, "NO", down_price, up_price, urgency, minutes_remaining
            )
        if has_no and not has_yes:
            return self._evaluate_completing_hedge(
                position, "YES", up_price, down_price, urgency, minutes_remaining
            )

        # CASE 3: Have both sides - add more if it improves pair_cost
        return self._evaluate_improving_position(position, up_price, down_price, urgency)

    def _evaluate_first_leg(
        self, up_price: float, down_price: float, minutes_remaining: float
    ) -> Optional[TradeSignal]:
        """
        Enter position when market is skewed.

        Entry conditions:
        - |UP - DOWN| > ENTRY_MIN_SKEW (0.60)
        - min(UP, DOWN) < ENTRY_MAX_CHEAP_PRICE (0.20)
        - minutes_remaining >= MIN_MINUTES_FOR_NEW_POSITION (8)
        """
        # Check timing - no new positions late in the window
        if minutes_remaining < config.MIN_MINUTES_FOR_NEW_POSITION:
            return None

        # Calculate skew
        skew = abs(up_price - down_price)
        min_price = min(up_price, down_price)

        # Check skew conditions
        if skew < config.ENTRY_MIN_SKEW:
            return None  # Market not skewed enough

        if min_price > config.ENTRY_MAX_CHEAP_PRICE:
            return None  # Cheap side not cheap enough

        if min_price < config.MIN_BUY_PRICE:
            return None  # Too illiquid

        # Buy the cheap side
        if up_price <= down_price:
            side, price = "YES", up_price
        else:
            side, price = "NO", down_price

        return TradeSignal(
            side=side,
            price=price,
            quantity=self.max_shares_per_order,
            reason=f"ENTRY: {side} @ ${price:.2f} (skew={skew:.2f}, {minutes_remaining:.0f}m left)",
            urgency="normal",
        )

    def _evaluate_completing_hedge(
        self,
        position: MarketPosition,
        side: str,
        price: float,
        other_price: float,
        urgency: str,
        minutes_remaining: float,
    ) -> Optional[TradeSignal]:
        """
        Complete the hedge by buying the other side.

        Allow expensive hedge legs (up to MAX_HEDGE_PRICE = 0.85)
        as long as simulated pair_cost <= max for urgency level.
        """
        # Price bounds
        if price < config.MIN_BUY_PRICE:
            return None  # Too illiquid
        if price > config.MAX_HEDGE_PRICE:
            return None  # Too expensive even for hedge

        # Get max acceptable pair_cost for this urgency
        max_pair_cost = self._get_max_pair_cost(urgency)

        # Match quantity to other side for balanced hedge
        other_qty = position.qty_yes if side == "NO" else position.qty_no
        qty = min(other_qty, self.max_shares_per_order)

        if qty < self.min_shares_per_order:
            return None

        # Simulate the pair_cost after this buy
        simulated_pair_cost = self._simulate_pair_cost(position, side, price, qty)

        if simulated_pair_cost > max_pair_cost:
            return None  # Would exceed max pair_cost for this urgency

        # Calculate expected P&L per share
        pnl_per_share = 1.0 - simulated_pair_cost

        # Build reason string
        if pnl_per_share >= 0:
            reason = f"[{urgency.upper()}] HEDGE {side} @ ${price:.2f} → pair=${simulated_pair_cost:.3f} (+${pnl_per_share:.3f}/sh)"
        else:
            reason = f"[{urgency.upper()}] HEDGE {side} @ ${price:.2f} → pair=${simulated_pair_cost:.3f} ({pnl_per_share:.3f}/sh)"

        return TradeSignal(
            side=side,
            price=price,
            quantity=qty,
            reason=reason,
            urgency=urgency,
        )

    def _evaluate_improving_position(
        self,
        position: MarketPosition,
        up_price: float,
        down_price: float,
        urgency: str,
    ) -> Optional[TradeSignal]:
        """Add to position if it improves pair_cost (already hedged)."""
        max_pair_cost = self._get_max_pair_cost(urgency)

        # Check if adding YES would improve things
        yes_signal = self._check_improvement(position, "YES", up_price, max_pair_cost)
        no_signal = self._check_improvement(position, "NO", down_price, max_pair_cost)

        if yes_signal and no_signal:
            return yes_signal if yes_signal.price < no_signal.price else no_signal
        return yes_signal or no_signal

    def _check_improvement(
        self,
        position: MarketPosition,
        side: str,
        price: float,
        max_pair_cost: float,
    ) -> Optional[TradeSignal]:
        """Check if adding to this side would improve pair_cost."""
        our_avg = position.avg_yes if side == "YES" else position.avg_no

        # Only buy if price is better than our current average
        if price >= our_avg:
            return None

        qty = self.min_shares_per_order
        new_pair_cost = self._simulate_pair_cost(position, side, price, qty)

        if new_pair_cost >= position.pair_cost:
            return None  # Wouldn't improve
        if new_pair_cost > max_pair_cost:
            return None  # Would exceed threshold

        return TradeSignal(
            side=side,
            price=price,
            quantity=qty,
            reason=f"IMPROVE: pair ${position.pair_cost:.3f} → ${new_pair_cost:.3f}",
        )

    def get_status(self, position: MarketPosition, up_price: float, down_price: float) -> str:
        """Get human-readable strategy status for a position."""
        skew = abs(up_price - down_price)
        min_price = min(up_price, down_price)

        if not position.qty_yes and not position.qty_no:
            if skew >= config.ENTRY_MIN_SKEW and min_price <= config.ENTRY_MAX_CHEAP_PRICE:
                return f"READY - Skew={skew:.2f}, cheap=${min_price:.2f}"
            return f"WAITING - Skew={skew:.2f} (need >{config.ENTRY_MIN_SKEW:.2f})"

        if not position.is_hedged:
            side = "YES" if position.qty_yes > 0 else "NO"
            avg = position.avg_yes if position.qty_yes > 0 else position.avg_no
            return f"UNHEDGED - {side} @ ${avg:.3f}, need other side"

        pnl = position.expected_pnl
        if pnl >= 0:
            return f"HEDGED - pair=${position.pair_cost:.3f}, +${pnl:.2f}"
        else:
            return f"HEDGED - pair=${position.pair_cost:.3f}, {pnl:.2f}"

"""
Gabagool Strategy: Continuous delta-neutral hedging.

Based on analysis of gabagool22's trading patterns:
1. Buy BOTH sides of every market continuously
2. Target pair_cost near $1.00 (accept breakeven or small loss)
3. Small order sizes (~15 shares)
4. High frequency - trade on every price update
5. No skew requirements - just accumulate both sides
"""

from dataclasses import dataclass
from typing import Optional

import config
from position_tracker import MarketPosition


@dataclass
class TradeSignal:
    """Signal to execute a trade."""
    side: str  # "YES" or "NO"
    price: float
    quantity: float
    reason: str
    urgency: str = "normal"


class GabagoolStrategy:
    """
    Continuous hedging strategy - buy both sides to create delta-neutral positions.

    Logic:
    1. If no position: buy the cheaper side
    2. If one side only: buy the other side to hedge
    3. If both sides: buy whichever improves balance or pair_cost
    4. Always check that simulated pair_cost <= max for urgency level
    """

    def __init__(
        self,
        min_shares_per_order: float = 5.0,
        max_shares_per_order: float = 15.0,
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

    def _is_valid_price(self, price: float) -> bool:
        """Check if price is within acceptable range."""
        return config.MIN_BUY_PRICE <= price <= config.MAX_BUY_PRICE

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

        # If one side has no position, estimate with current price
        if new_avg_yes == 0 or new_avg_no == 0:
            return price  # Can't calculate full pair cost yet

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

        Gabagool style: Always try to buy both sides, keep positions balanced.
        """
        # Don't trade in last minute
        if minutes_remaining < config.MIN_MINUTES_FOR_NEW_POSITION:
            return None

        has_yes = position.qty_yes > 0
        has_no = position.qty_no > 0
        urgency = self._get_urgency_level(minutes_remaining)
        max_pair_cost = self._get_max_pair_cost(urgency)

        # CASE 1: No position - buy the cheaper side
        if not has_yes and not has_no:
            return self._buy_cheaper_side(up_price, down_price, urgency)

        # CASE 2: Have YES only - buy NO to hedge
        if has_yes and not has_no:
            return self._buy_to_hedge(position, "NO", down_price, urgency, max_pair_cost)

        # CASE 3: Have NO only - buy YES to hedge
        if has_no and not has_yes:
            return self._buy_to_hedge(position, "YES", up_price, urgency, max_pair_cost)

        # CASE 4: Have both - buy to balance or improve
        return self._buy_to_balance(position, up_price, down_price, urgency, max_pair_cost)

    def _buy_cheaper_side(
        self, up_price: float, down_price: float, urgency: str
    ) -> Optional[TradeSignal]:
        """Buy the cheaper side to start a position."""
        # Determine which side is cheaper
        if up_price <= down_price:
            side, price = "YES", up_price
        else:
            side, price = "NO", down_price

        if not self._is_valid_price(price):
            return None

        return TradeSignal(
            side=side,
            price=price,
            quantity=self.max_shares_per_order,
            reason=f"ENTRY: Buy {side} @ ${price:.3f} (cheaper side)",
            urgency=urgency,
        )

    def _buy_to_hedge(
        self,
        position: MarketPosition,
        side: str,
        price: float,
        urgency: str,
        max_pair_cost: float,
    ) -> Optional[TradeSignal]:
        """Buy the other side to complete the hedge."""
        if not self._is_valid_price(price):
            return None

        # Match quantity to create balanced position
        other_qty = position.qty_yes if side == "NO" else position.qty_no
        qty = min(other_qty, self.max_shares_per_order)

        if qty < self.min_shares_per_order:
            qty = self.min_shares_per_order

        # Simulate pair cost
        simulated_pair_cost = self._simulate_pair_cost(position, side, price, qty)

        # For hedging, be more lenient - we need to complete the hedge
        if simulated_pair_cost > max_pair_cost + 0.01:  # Allow slightly above max
            return None

        pnl = 1.0 - simulated_pair_cost
        pnl_str = f"+${pnl:.3f}" if pnl >= 0 else f"-${abs(pnl):.3f}"

        return TradeSignal(
            side=side,
            price=price,
            quantity=qty,
            reason=f"HEDGE: {side} @ ${price:.3f} → pair ${simulated_pair_cost:.3f} ({pnl_str}/sh)",
            urgency=urgency,
        )

    def _buy_to_balance(
        self,
        position: MarketPosition,
        up_price: float,
        down_price: float,
        urgency: str,
        max_pair_cost: float,
    ) -> Optional[TradeSignal]:
        """Buy to balance position or improve pair_cost."""
        # Determine which side needs more shares for balance
        imbalance = position.qty_yes - position.qty_no

        if abs(imbalance) < self.min_shares_per_order:
            # Position is balanced - buy whichever is cheaper if it improves pair_cost
            return self._buy_if_improves(position, up_price, down_price, urgency, max_pair_cost)

        if imbalance > 0:
            # More YES than NO - buy NO
            side, price = "NO", down_price
            qty = min(imbalance, self.max_shares_per_order)
        else:
            # More NO than YES - buy YES
            side, price = "YES", up_price
            qty = min(abs(imbalance), self.max_shares_per_order)

        if not self._is_valid_price(price):
            return None

        if qty < self.min_shares_per_order:
            qty = self.min_shares_per_order

        # Check pair cost
        simulated_pair_cost = self._simulate_pair_cost(position, side, price, qty)

        if simulated_pair_cost > max_pair_cost:
            return None

        return TradeSignal(
            side=side,
            price=price,
            quantity=qty,
            reason=f"BALANCE: {side} @ ${price:.3f} (imbalance: {imbalance:.0f})",
            urgency=urgency,
        )

    def _buy_if_improves(
        self,
        position: MarketPosition,
        up_price: float,
        down_price: float,
        urgency: str,
        max_pair_cost: float,
    ) -> Optional[TradeSignal]:
        """Buy if it improves our average (only when balanced)."""
        # Check if buying YES improves our average
        yes_signal = None
        no_signal = None

        if self._is_valid_price(up_price) and up_price < position.avg_yes:
            new_pair = self._simulate_pair_cost(position, "YES", up_price, self.min_shares_per_order)
            if new_pair < position.pair_cost and new_pair <= max_pair_cost:
                yes_signal = TradeSignal(
                    side="YES",
                    price=up_price,
                    quantity=self.min_shares_per_order,
                    reason=f"IMPROVE: YES @ ${up_price:.3f} (< avg ${position.avg_yes:.3f})",
                    urgency=urgency,
                )

        if self._is_valid_price(down_price) and down_price < position.avg_no:
            new_pair = self._simulate_pair_cost(position, "NO", down_price, self.min_shares_per_order)
            if new_pair < position.pair_cost and new_pair <= max_pair_cost:
                no_signal = TradeSignal(
                    side="NO",
                    price=down_price,
                    quantity=self.min_shares_per_order,
                    reason=f"IMPROVE: NO @ ${down_price:.3f} (< avg ${position.avg_no:.3f})",
                    urgency=urgency,
                )

        # Return whichever improves more (lower price = better improvement)
        if yes_signal and no_signal:
            return yes_signal if up_price < down_price else no_signal
        return yes_signal or no_signal

    def get_status(self, position: MarketPosition, up_price: float, down_price: float) -> str:
        """Get human-readable strategy status for a position."""
        if not position.qty_yes and not position.qty_no:
            cheaper = "YES" if up_price <= down_price else "NO"
            cheaper_price = min(up_price, down_price)
            return f"NO POSITION - Will buy {cheaper} @ ${cheaper_price:.3f}"

        if not position.is_hedged:
            side = "YES" if position.qty_yes > 0 else "NO"
            other = "NO" if side == "YES" else "YES"
            other_price = down_price if side == "YES" else up_price
            return f"UNHEDGED - Have {side}, need {other} @ ${other_price:.3f}"

        imbalance = position.qty_yes - position.qty_no
        pnl = position.expected_pnl
        pnl_str = f"+${pnl:.3f}" if pnl >= 0 else f"${pnl:.3f}"

        if abs(imbalance) < 5:
            return f"HEDGED - pair ${position.pair_cost:.3f}, P&L {pnl_str}/sh"
        else:
            need = "NO" if imbalance > 0 else "YES"
            return f"IMBALANCED - need {abs(imbalance):.0f} more {need}"

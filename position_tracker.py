"""Position tracking for the gabagool asymmetric hedging strategy."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class MarketPosition:
    """Tracks cumulative positions for a single market."""
    market_id: str
    market_name: str = ""
    qty_yes: float = 0.0
    qty_no: float = 0.0
    cost_yes: float = 0.0
    cost_no: float = 0.0
    trades: list = field(default_factory=list)

    @property
    def avg_yes(self) -> float:
        """Average cost per YES share."""
        return self.cost_yes / self.qty_yes if self.qty_yes > 0 else 0.0

    @property
    def avg_no(self) -> float:
        """Average cost per NO share."""
        return self.cost_no / self.qty_no if self.qty_no > 0 else 0.0

    @property
    def pair_cost(self) -> float:
        """Combined average cost (avg_YES + avg_NO)."""
        if self.qty_yes > 0 and self.qty_no > 0:
            return self.avg_yes + self.avg_no
        return 0.0

    @property
    def total_cost(self) -> float:
        """Total dollars spent."""
        return self.cost_yes + self.cost_no

    @property
    def hedged_qty(self) -> float:
        """Number of shares that are fully hedged (min of YES and NO)."""
        return min(self.qty_yes, self.qty_no)

    @property
    def is_hedged(self) -> bool:
        """True if we have both YES and NO positions."""
        return self.qty_yes > 0 and self.qty_no > 0

    @property
    def is_profitable(self) -> bool:
        """True if pair_cost < 1.0 and we're hedged."""
        return self.is_hedged and self.pair_cost < 1.0

    @property
    def guaranteed_profit(self) -> float:
        """
        Guaranteed profit if market resolves.
        = hedged_qty * 1.0 - total_cost_for_hedged_portion
        """
        if not self.is_hedged:
            return 0.0
        hedged = self.hedged_qty
        # Cost for the hedged portion (proportional)
        cost_for_hedged = (self.avg_yes + self.avg_no) * hedged
        return hedged - cost_for_hedged

    @property
    def expected_pnl(self) -> float:
        """
        Expected P&L per share (can be negative).
        For loss-bounded inventory rebalancing, we accept small losses.
        = 1.0 - pair_cost
        """
        if not self.is_hedged:
            return 0.0
        return 1.0 - self.pair_cost

    @property
    def imbalance(self) -> float:
        """How unbalanced the position is (abs difference / avg)."""
        if self.qty_yes == 0 and self.qty_no == 0:
            return 0.0
        total = self.qty_yes + self.qty_no
        if total == 0:
            return 0.0
        return abs(self.qty_yes - self.qty_no) / (total / 2)

    def record_buy_yes(self, price: float, qty: float):
        """Record a YES purchase."""
        self.qty_yes += qty
        self.cost_yes += price * qty
        self.trades.append({
            "side": "YES",
            "price": price,
            "qty": qty,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def record_buy_no(self, price: float, qty: float):
        """Record a NO purchase."""
        self.qty_no += qty
        self.cost_no += price * qty
        self.trades.append({
            "side": "NO",
            "price": price,
            "qty": qty,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def summary(self) -> str:
        """Human-readable position summary."""
        if not self.is_hedged:
            if self.qty_yes > 0:
                return f"YES={self.qty_yes:.1f} @ ${self.avg_yes:.4f} | NO=0 | NOT HEDGED"
            elif self.qty_no > 0:
                return f"YES=0 | NO={self.qty_no:.1f} @ ${self.avg_no:.4f} | NOT HEDGED"
            else:
                return "NO POSITION"

        profit_str = f"PROFIT: ${self.guaranteed_profit:.2f}" if self.is_profitable else "NOT PROFITABLE"
        return (
            f"YES={self.qty_yes:.1f} @ ${self.avg_yes:.4f} | "
            f"NO={self.qty_no:.1f} @ ${self.avg_no:.4f} | "
            f"PAIR_COST: {self.pair_cost:.4f} | {profit_str}"
        )


class PositionTracker:
    """Manages positions across multiple markets."""

    def __init__(self):
        self.positions: dict[str, MarketPosition] = {}
        self.closed_positions: list[MarketPosition] = []

    def get_position(self, market_id: str, market_name: str = "") -> MarketPosition:
        """Get or create a position for a market."""
        if market_id not in self.positions:
            self.positions[market_id] = MarketPosition(
                market_id=market_id,
                market_name=market_name
            )
        return self.positions[market_id]

    def record_buy(self, market_id: str, side: str, price: float, qty: float, market_name: str = ""):
        """Record a buy order."""
        position = self.get_position(market_id, market_name)
        if side.upper() == "YES":
            position.record_buy_yes(price, qty)
        elif side.upper() == "NO":
            position.record_buy_no(price, qty)

    def close_market(self, market_id: str, winning_side: str) -> Optional[float]:
        """
        Close a market position when it resolves.
        Returns the realized P&L.
        """
        if market_id not in self.positions:
            return None

        position = self.positions[market_id]

        # Calculate P&L
        if winning_side.upper() == "YES":
            payout = position.qty_yes * 1.0  # $1 per winning share
        else:
            payout = position.qty_no * 1.0

        pnl = payout - position.total_cost

        # Move to closed
        self.closed_positions.append(position)
        del self.positions[market_id]

        return pnl

    def total_exposure(self) -> float:
        """Total dollars currently at risk."""
        return sum(p.total_cost for p in self.positions.values())

    def total_guaranteed_profit(self) -> float:
        """Total guaranteed profit across all hedged positions."""
        return sum(p.guaranteed_profit for p in self.positions.values() if p.is_profitable)

    def summary(self) -> str:
        """Summary of all open positions."""
        if not self.positions:
            return "No open positions"

        lines = ["=== OPEN POSITIONS ==="]
        for market_id, pos in self.positions.items():
            lines.append(f"  {pos.market_name or market_id[:20]}: {pos.summary()}")

        lines.append(f"  TOTAL EXPOSURE: ${self.total_exposure():.2f}")
        lines.append(f"  TOTAL GUARANTEED PROFIT: ${self.total_guaranteed_profit():.2f}")
        return "\n".join(lines)

"""Order execution for the trading bot (paper and live modes)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class OrderResult:
    """Result of an order execution."""
    order_id: str
    token_id: str
    side: str  # "YES" or "NO"
    price: float
    size: float
    status: str  # "FILLED", "PENDING", "REJECTED"
    filled_at: Optional[str] = None
    error: Optional[str] = None


class OrderExecutor(ABC):
    """Abstract base class for order execution."""

    @abstractmethod
    def buy_shares(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        market_name: str = "",
    ) -> OrderResult:
        """Execute a buy order."""
        pass

    @abstractmethod
    def get_balance(self) -> float:
        """Get current USDC balance."""
        pass


class PaperOrderExecutor(OrderExecutor):
    """
    Simulates order execution for paper trading.

    Orders are instantly filled at the requested price.
    Tracks simulated balance and order history.
    """

    def __init__(self, initial_balance: float = 100.0):
        """
        Initialize paper trading executor.

        Args:
            initial_balance: Starting USDC balance for simulation
        """
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.order_id_counter = 0
        self.orders: list[OrderResult] = []
        self.total_spent = 0.0
        self.total_shares_bought = 0.0

    def buy_shares(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        market_name: str = "",
    ) -> OrderResult:
        """
        Simulate a buy order (instant fill at requested price).

        Args:
            token_id: The token ID to buy
            side: "YES" or "NO"
            price: Price per share
            size: Number of shares
            market_name: Human-readable market name for logging

        Returns:
            OrderResult with fill details
        """
        self.order_id_counter += 1
        order_id = f"PAPER-{self.order_id_counter:05d}"

        cost = price * size

        # Check if we have enough balance
        if cost > self.balance:
            return OrderResult(
                order_id=order_id,
                token_id=token_id,
                side=side,
                price=price,
                size=size,
                status="REJECTED",
                error=f"Insufficient balance: need ${cost:.2f}, have ${self.balance:.2f}",
            )

        # Execute the "trade"
        self.balance -= cost
        self.total_spent += cost
        self.total_shares_bought += size

        result = OrderResult(
            order_id=order_id,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            status="FILLED",
            filled_at=datetime.now(timezone.utc).isoformat(),
        )

        self.orders.append(result)

        # Log the trade
        market_str = f" ({market_name})" if market_name else ""
        print(f"  [PAPER] BUY {size:.1f} {side} @ ${price:.4f} = ${cost:.2f}{market_str}")
        print(f"          Balance: ${self.balance:.2f} remaining")

        return result

    def get_balance(self) -> float:
        """Get current simulated balance."""
        return self.balance

    def get_stats(self) -> dict:
        """Get trading statistics."""
        return {
            "initial_balance": self.initial_balance,
            "current_balance": self.balance,
            "total_spent": self.total_spent,
            "total_orders": len(self.orders),
            "total_shares": self.total_shares_bought,
            "filled_orders": len([o for o in self.orders if o.status == "FILLED"]),
            "rejected_orders": len([o for o in self.orders if o.status == "REJECTED"]),
        }

    def summary(self) -> str:
        """Get human-readable summary."""
        stats = self.get_stats()
        return (
            f"Paper Trading Summary:\n"
            f"  Initial Balance: ${stats['initial_balance']:.2f}\n"
            f"  Current Balance: ${stats['current_balance']:.2f}\n"
            f"  Total Spent: ${stats['total_spent']:.2f}\n"
            f"  Total Orders: {stats['total_orders']} "
            f"({stats['filled_orders']} filled, {stats['rejected_orders']} rejected)\n"
            f"  Total Shares: {stats['total_shares']:.1f}"
        )


class LiveOrderExecutor(OrderExecutor):
    """
    Real order execution via Polymarket CLOB API.

    NOTE: This is a placeholder for future live trading implementation.
    Requires proper wallet setup and API credentials.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str,
        private_key: str,
    ):
        """
        Initialize live trading executor.

        Args:
            api_key: Polymarket API key
            api_secret: Polymarket API secret
            passphrase: Polymarket API passphrase
            private_key: Wallet private key for signing
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.private_key = private_key
        self._client = None

        # We'll initialize the actual client when needed
        print("WARNING: Live trading not yet implemented. Use paper trading mode.")

    def _get_client(self):
        """Lazily initialize the CLOB client."""
        if self._client is None:
            try:
                from py_clob_client.client import ClobClient

                self._client = ClobClient(
                    host="https://clob.polymarket.com",
                    key=self.api_key,
                    secret=self.api_secret,
                    passphrase=self.passphrase,
                    chain_id=137,  # Polygon mainnet
                    signer=self.private_key,
                )
            except ImportError:
                raise RuntimeError(
                    "py-clob-client not installed. Run: pip install py-clob-client"
                )
            except Exception as e:
                raise RuntimeError(f"Failed to initialize CLOB client: {e}")

        return self._client

    def buy_shares(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        market_name: str = "",
    ) -> OrderResult:
        """
        Place a real buy order via Polymarket CLOB.

        NOTE: Not yet implemented for safety.
        """
        raise NotImplementedError(
            "Live trading not yet implemented. Use PaperOrderExecutor for testing."
        )

    def get_balance(self) -> float:
        """Get actual USDC balance from wallet."""
        raise NotImplementedError(
            "Live balance check not yet implemented."
        )


def create_executor(
    mode: str = "paper",
    initial_balance: float = 100.0,
    api_key: str = "",
    api_secret: str = "",
    passphrase: str = "",
    private_key: str = "",
) -> OrderExecutor:
    """
    Factory function to create the appropriate executor.

    Args:
        mode: "paper" or "live"
        initial_balance: Starting balance for paper trading
        api_key: Polymarket API key (for live mode)
        api_secret: Polymarket API secret (for live mode)
        passphrase: Polymarket passphrase (for live mode)
        private_key: Wallet private key (for live mode)

    Returns:
        Configured OrderExecutor instance
    """
    if mode == "paper":
        return PaperOrderExecutor(initial_balance=initial_balance)
    elif mode == "live":
        return LiveOrderExecutor(
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            private_key=private_key,
        )
    else:
        raise ValueError(f"Unknown executor mode: {mode}")

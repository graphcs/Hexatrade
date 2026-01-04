"""Configuration constants for Polymarket BTC monitor."""

import os
from dotenv import load_dotenv

load_dotenv()

# API Credentials
API_KEY = os.getenv("POLYMARKET_API_KEY", "")
API_SECRET = os.getenv("POLYMARKET_SECRET", "")
API_PASSPHRASE = os.getenv("POLYMARKET_PASSPHRASE", "")

# API Endpoints
CLOB_BASE_URL = "https://clob.polymarket.com"
WEBSOCKET_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# Alert Settings
ALERT_THRESHOLD = 1.00  # Alert when sum_price < this value

# Market Discovery
MARKET_REFRESH_INTERVAL = 300  # Refresh markets every 5 minutes (seconds)
BTC_MARKET_KEYWORDS = ["btc", "bitcoin", "up or down", "15"]

# Logging
LOG_FORMAT = "%(asctime)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"

# =============================================================================
# TRADING BOT CONFIGURATION (Gabagool Strategy)
# Skew-based inventory rebalancing with loss-bounded hedging
# =============================================================================

# Trading Mode
TRADING_MODE = "paper"  # "paper" for simulation, "live" for real trading
PAPER_TRADING_BALANCE = 100.0  # Starting balance for paper trading

# =============================================================================
# ENTRY CONDITIONS (Skew-Based)
# =============================================================================
# Only enter when market is skewed (one side cheaper than other)
ENTRY_MIN_SKEW = 0.10           # Enter when |UP - DOWN| > 10¢
ENTRY_MAX_CHEAP_PRICE = 0.50    # Cheap side must be < 50¢ to enter
MIN_BUY_PRICE = 0.05            # Don't buy if price below this (too illiquid)

# =============================================================================
# HEDGE CONDITIONS
# =============================================================================
# Allow expensive hedge legs to close out risk
MAX_HEDGE_PRICE = 0.85          # Allow hedge legs up to 85¢
MIN_SHARES_PER_ORDER = 5.0      # Minimum shares per trade
MAX_SHARES_PER_ORDER = 50.0     # Maximum shares per single order

# =============================================================================
# RISK MANAGEMENT
# =============================================================================
MAX_TOTAL_EXPOSURE = 100.0      # Maximum $ across all markets
MAX_PER_MARKET_EXPOSURE = 50.0  # Maximum $ per single market
MAX_UNHEDGED_MARKETS = 1        # Complete hedge before opening new position

# =============================================================================
# TIMING
# =============================================================================
# No new first legs after 7 min into window (need 8+ min remaining)
MIN_MINUTES_FOR_NEW_POSITION = 8
STOP_TRADING_BEFORE_CLOSE_MINUTES = 0  # Urgency handles late trading

# =============================================================================
# URGENCY LEVELS (Operating in 0.995-1.02 range)
# =============================================================================
# Real trading operates near pair_cost = 1.0, not 0.97
URGENCY_THRESHOLDS = {
    "normal": {"minutes": 10, "max_pair_cost": 0.995},   # > 10 min: target small profit
    "eager": {"minutes": 5, "max_pair_cost": 1.005},     # 5-10 min: accept tiny loss
    "urgent": {"minutes": 2, "max_pair_cost": 1.01},     # 2-5 min: accept 1% loss
    "emergency": {"minutes": 0, "max_pair_cost": 1.02},  # < 2 min: accept 2% loss
}

# Wallet (for live trading - not used in paper mode)
PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "")

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
# ENTRY CONDITIONS (Gabagool Style - Continuous Hedging)
# =============================================================================
# Buy both sides continuously, don't wait for skew
MIN_BUY_PRICE = 0.03            # Don't buy below 3¢ (too illiquid)
MAX_BUY_PRICE = 0.97            # Don't buy above 97¢ (too expensive)

# =============================================================================
# PAIR COST TARGETING
# =============================================================================
# Target pair cost near $1.00 - accept breakeven or small loss
TARGET_PAIR_COST = 1.00         # Target pair cost
MAX_PAIR_COST = 1.02            # Maximum acceptable pair cost (2% loss max)

# =============================================================================
# ORDER SIZING (Gabagool uses ~15 shares per order)
# =============================================================================
MIN_SHARES_PER_ORDER = 5.0      # Minimum shares per trade
MAX_SHARES_PER_ORDER = 15.0     # Keep orders small like Gabagool

# =============================================================================
# RISK MANAGEMENT
# =============================================================================
MAX_TOTAL_EXPOSURE = 100.0      # Maximum $ across all markets
MAX_PER_MARKET_EXPOSURE = 50.0  # Maximum $ per single market
MAX_UNHEDGED_MARKETS = 1        # Complete hedge before opening new position

# =============================================================================
# TIMING (Gabagool trades continuously, no restrictions)
# =============================================================================
MIN_MINUTES_FOR_NEW_POSITION = 1    # Trade until last minute
STOP_TRADING_BEFORE_CLOSE_MINUTES = 0

# =============================================================================
# URGENCY LEVELS (Gabagool accepts pair_cost up to ~1.03)
# =============================================================================
URGENCY_THRESHOLDS = {
    "normal": {"minutes": 10, "max_pair_cost": 1.00},    # > 10 min: target breakeven
    "eager": {"minutes": 5, "max_pair_cost": 1.01},      # 5-10 min: accept 1% loss
    "urgent": {"minutes": 2, "max_pair_cost": 1.02},     # 2-5 min: accept 2% loss
    "emergency": {"minutes": 0, "max_pair_cost": 1.03},  # < 2 min: accept 3% loss
}

# Wallet (for live trading - not used in paper mode)
PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "")

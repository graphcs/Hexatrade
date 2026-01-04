# Hexatrade - Polymarket BTC 15-Minute Trading Bot

A terminal-based trading bot for Polymarket's BTC 15-minute prediction markets using the "Gabagool" strategy - a delta-neutral hedging approach that aims to profit regardless of market outcome.

## Strategy Overview

The Gabagool strategy exploits price inefficiencies in binary prediction markets:

1. **Entry**: When market is skewed (one side cheaper than the other), buy the cheap side
2. **Hedge**: Buy the opposite side to create a delta-neutral position
3. **Profit**: If `avg_YES + avg_NO < $1.00`, you profit regardless of outcome (since winning side pays $1.00)

### Example
```
Buy 50 YES @ $0.45 = $22.50
Buy 50 NO  @ $0.52 = $26.00
Total cost: $48.50

Outcome (either way): 50 shares x $1.00 = $50.00
Profit: $1.50 (guaranteed)
```

### Urgency Levels
As market close approaches, the bot accepts higher pair costs:
- **Normal** (>10 min): max pair cost 0.995 (small profit)
- **Eager** (5-10 min): max pair cost 1.005 (tiny loss acceptable)
- **Urgent** (2-5 min): max pair cost 1.01 (1% loss acceptable)
- **Emergency** (<2 min): max pair cost 1.02 (2% loss to close position)

## Features

- Real-time price streaming via WebSocket
- Terminal UI (TUI) with live prices, positions, and P&L
- Paper trading mode for testing
- Risk management (exposure limits, position limits)
- Automatic market discovery for BTC 15-minute markets

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd hexatrade

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Configuration

Copy the example environment file and configure:

```bash
cp .env.example .env
```

Edit `.env` with your credentials (only needed for live trading):
```
POLYMARKET_API_KEY=your_api_key
POLYMARKET_SECRET=your_secret
POLYMARKET_PASSPHRASE=your_passphrase
WALLET_PRIVATE_KEY=your_wallet_private_key
```

### Key Settings (in `config.py`)

```python
# Trading mode
TRADING_MODE = "paper"          # "paper" or "live"
PAPER_TRADING_BALANCE = 100.0   # Starting balance for paper trading

# Entry conditions
ENTRY_MIN_SKEW = 0.10           # Minimum price difference to enter
ENTRY_MAX_CHEAP_PRICE = 0.50    # Max price for cheap side

# Risk limits
MAX_TOTAL_EXPOSURE = 100.0      # Max $ across all markets
MAX_PER_MARKET_EXPOSURE = 50.0  # Max $ per market
MAX_UNHEDGED_MARKETS = 1        # Complete hedge before new position
```

## Usage

### Run the bot
```bash
source venv/bin/activate
python main.py
```

### TUI Layout
```
┌─────────────────────────────────────────────────────────────┐
│ Open Positions          │ Summary        │ Recent Activity  │
│ - Market positions      │ - Balance      │ - Trade logs     │
│ - P&L per position      │ - Exposure     │ - Blocked trades │
│                         │ - Expected P&L │                  │
├─────────────────────────────────────────────────────────────┤
│                    LIVE MARKET PRICES                       │
│ MARKET          YES        NO       SUM      SKEW   SIGNAL  │
│ BTC-15M-00AM   $0.5600   $0.4500   $1.0100  $0.11  BUY NO   │
└─────────────────────────────────────────────────────────────┘
```

### Controls
- `Ctrl+C` - Graceful shutdown with final summary

## Project Structure

```
hexatrade/
├── main.py              # Entry point, orchestrates components
├── config.py            # Configuration constants
├── trading_strategy.py  # Gabagool strategy implementation
├── position_tracker.py  # Tracks positions and calculates P&L
├── risk_manager.py      # Enforces trading limits
├── order_executor.py    # Paper/live order execution
├── market_discovery.py  # Finds active BTC 15-min markets
├── price_monitor.py     # Processes price updates
├── websocket_client.py  # WebSocket connection to Polymarket
├── tui.py              # Terminal user interface
└── requirements.txt     # Python dependencies
```

## How It Works

1. **Market Discovery**: Finds active BTC 15-minute prediction markets on Polymarket
2. **WebSocket Connection**: Subscribes to real-time price updates
3. **Strategy Evaluation**: On each price update, evaluates if entry/hedge conditions are met
4. **Risk Check**: Validates trade against exposure limits
5. **Execution**: Places order (paper or live)
6. **Position Tracking**: Updates positions and calculates guaranteed profit

## Risk Warnings

- This is experimental software for educational purposes
- Paper trading mode is recommended for testing
- Past performance does not guarantee future results
- Only trade with funds you can afford to lose
- Polymarket may have terms of service restrictions in your jurisdiction

## Dependencies

- `rich` - Terminal UI
- `websockets` - WebSocket client
- `requests` - HTTP client
- `python-dotenv` - Environment variable loading


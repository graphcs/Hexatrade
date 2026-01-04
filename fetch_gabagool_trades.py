#!/usr/bin/env python3
"""Fetch trade history for gabagool22 from Polymarket and save to CSV."""

import csv
import json
import time
import requests
from datetime import datetime

WALLET_ADDRESS = "0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d"
API_URL = "https://data-api.polymarket.com/activity"
OUTPUT_FILE = "gabagool22_trades.csv"
TARGET_TRADES = 1000
BATCH_SIZE = 100


def fetch_trades(offset=0, limit=100):
    """Fetch a batch of trades from the API."""
    params = {
        "user": WALLET_ADDRESS,
        "limit": limit,
        "offset": offset,
    }
    response = requests.get(API_URL, params=params)
    response.raise_for_status()
    return response.json()


def parse_trade(trade):
    """Extract relevant fields from a trade."""
    timestamp = trade.get("timestamp", 0)
    dt = datetime.fromtimestamp(timestamp) if timestamp else None

    return {
        "timestamp": dt.isoformat() if dt else "",
        "timestamp_unix": timestamp,
        "type": trade.get("type", ""),
        "side": trade.get("side", ""),
        "outcome": trade.get("outcome", ""),
        "size": trade.get("size", 0),
        "price": trade.get("price", 0),
        "usdc_size": trade.get("usdcSize", 0),
        "title": trade.get("title", ""),
        "slug": trade.get("slug", ""),
        "condition_id": trade.get("conditionId", ""),
        "asset": trade.get("asset", ""),
        "outcome_index": trade.get("outcomeIndex", ""),
        "transaction_hash": trade.get("transactionHash", ""),
    }


def main():
    print(f"Fetching trades for gabagool22 ({WALLET_ADDRESS})")
    print(f"Target: {TARGET_TRADES} trades\n")

    all_trades = []
    offset = 0

    while len(all_trades) < TARGET_TRADES:
        print(f"Fetching trades {offset} - {offset + BATCH_SIZE}...")

        try:
            trades = fetch_trades(offset=offset, limit=BATCH_SIZE)
        except Exception as e:
            print(f"Error fetching trades: {e}")
            break

        if not trades:
            print("No more trades available")
            break

        all_trades.extend(trades)
        offset += BATCH_SIZE

        print(f"  Got {len(trades)} trades, total: {len(all_trades)}")

        # Rate limiting
        time.sleep(0.5)

    # Trim to target
    all_trades = all_trades[:TARGET_TRADES]

    print(f"\nProcessing {len(all_trades)} trades...")

    # Parse trades
    parsed_trades = [parse_trade(t) for t in all_trades]

    # Write to CSV
    if parsed_trades:
        fieldnames = parsed_trades[0].keys()

        with open(OUTPUT_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(parsed_trades)

        print(f"\nSaved {len(parsed_trades)} trades to {OUTPUT_FILE}")

        # Print summary stats
        buy_count = sum(1 for t in parsed_trades if t["side"] == "BUY")
        sell_count = sum(1 for t in parsed_trades if t["side"] == "SELL")
        total_volume = sum(float(t["usdc_size"]) for t in parsed_trades)

        print(f"\nSummary:")
        print(f"  Buys: {buy_count}")
        print(f"  Sells: {sell_count}")
        print(f"  Total Volume: ${total_volume:,.2f}")

        # Date range
        if parsed_trades:
            first_date = parsed_trades[-1]["timestamp"]
            last_date = parsed_trades[0]["timestamp"]
            print(f"  Date Range: {first_date} to {last_date}")
    else:
        print("No trades found!")


if __name__ == "__main__":
    main()

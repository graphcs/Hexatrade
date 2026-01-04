"""WebSocket client for real-time Polymarket price updates."""

import json
import threading
import time
from typing import Callable, Optional

from websocket import WebSocketApp

import config


class PolymarketWebSocket:
    """WebSocket client for subscribing to Polymarket market data."""

    def __init__(self, on_price_update: Callable[[dict], None]):
        self.on_price_update = on_price_update
        self.ws: Optional[WebSocketApp] = None
        self.subscribed_assets: list[str] = []
        self.is_connected = False
        self.reconnect_delay = 1
        self.max_reconnect_delay = 60
        self._stop_event = threading.Event()
        self._ws_thread: Optional[threading.Thread] = None

    def connect(self, asset_ids: list[str]):
        """Connect to WebSocket and subscribe to asset IDs."""
        self.subscribed_assets = asset_ids
        self._stop_event.clear()

        self.ws = WebSocketApp(
            config.WEBSOCKET_URL,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
        )

        self._ws_thread = threading.Thread(target=self._run_forever, daemon=True)
        self._ws_thread.start()

    def _run_forever(self):
        """Run WebSocket with automatic reconnection."""
        while not self._stop_event.is_set():
            try:
                self.ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                print(f"WebSocket error: {e}")

            if self._stop_event.is_set():
                break

            print(f"Reconnecting in {self.reconnect_delay}s...")
            time.sleep(self.reconnect_delay)
            self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)

    def _on_open(self, ws):
        """Handle WebSocket connection open."""
        self.is_connected = True
        self.reconnect_delay = 1
        print(f"WebSocket connected. Subscribing to {len(self.subscribed_assets)} assets...")

        subscribe_msg = {
            "assets_ids": self.subscribed_assets,
            "type": "market"
        }
        ws.send(json.dumps(subscribe_msg))

    def _on_message(self, ws, message: str):
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
            self.on_price_update(data)
        except json.JSONDecodeError as e:
            print(f"Failed to parse message: {e}")

    def _on_error(self, ws, error):
        """Handle WebSocket error."""
        print(f"WebSocket error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket connection close."""
        self.is_connected = False
        print(f"WebSocket closed: {close_status_code} - {close_msg}")

    def update_subscriptions(self, new_asset_ids: list[str]):
        """Update subscriptions with new asset IDs."""
        new_ids = set(new_asset_ids) - set(self.subscribed_assets)
        if new_ids and self.is_connected and self.ws:
            self.subscribed_assets.extend(list(new_ids))
            subscribe_msg = {
                "assets_ids": list(new_ids),
                "type": "market"
            }
            self.ws.send(json.dumps(subscribe_msg))
            print(f"Subscribed to {len(new_ids)} new assets")

    def stop(self):
        """Stop the WebSocket connection."""
        self._stop_event.set()
        if self.ws:
            self.ws.close()

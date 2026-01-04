"""Terminal User Interface for the trading bot."""

import threading
import time
from datetime import datetime, timezone
from typing import Optional

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import config
from position_tracker import PositionTracker
from order_executor import PaperOrderExecutor


class TradingTUI:
    """Rich-based TUI for displaying trading bot status."""

    def __init__(
        self,
        position_tracker: PositionTracker,
        executor: PaperOrderExecutor,
        max_exposure: float = 100.0,
    ):
        self.position_tracker = position_tracker
        self.executor = executor
        self.max_exposure = max_exposure
        self.console = Console()

        # Price data: {market_id: {name, up, down, sum, updated}}
        self.prices: dict[str, dict] = {}
        self.price_lock = threading.Lock()

        # Recent activity log
        self.activity_log: list[str] = []
        self.max_log_entries = 8

        # Stats
        self.start_time = datetime.now(timezone.utc)
        self.price_updates = 0

        # Live display
        self._live: Optional[Live] = None
        self._running = False

    def update_price(
        self,
        market_id: str,
        market_name: str,
        up_price: float,
        down_price: float,
        sum_price: float,
    ):
        """Update price data for a market."""
        with self.price_lock:
            self.prices[market_id] = {
                "name": market_name,
                "up": up_price,
                "down": down_price,
                "sum": sum_price,
                "updated": datetime.now(timezone.utc),
            }
            self.price_updates += 1

    def log_activity(self, message: str):
        """Add an entry to the activity log."""
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.activity_log.append(f"[dim]{timestamp}[/] {message}")
        if len(self.activity_log) > self.max_log_entries:
            self.activity_log.pop(0)

    def log_trade(self, side: str, qty: float, price: float, market_name: str, urgency: str = "normal"):
        """Log a trade execution with urgency level."""
        color = "green" if side == "YES" else "red"

        # Urgency indicator
        urgency_style = {
            "normal": "[dim]",
            "eager": "[yellow]",
            "urgent": "[bold yellow]",
            "emergency": "[bold red]",
        }.get(urgency, "[dim]")

        urgency_suffix = "" if urgency == "normal" else f" {urgency_style}[{urgency.upper()}][/]"

        self.log_activity(
            f"[bold {color}]BUY {qty:.1f} {side}[/] @ ${price:.4f}{urgency_suffix}"
        )

    def _make_footer(self) -> Panel:
        """Create the footer status bar."""
        elapsed = datetime.now(timezone.utc) - self.start_time
        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)

        # Use fixed-width formatting to prevent layout shifts
        updates_str = f"{self.price_updates:>8,}"

        footer_text = Text(justify="center")
        footer_text.append("POLYMARKET BTC 15M", style="bold cyan")
        footer_text.append("  |  ", style="dim")
        footer_text.append("Gabagool", style="yellow")
        footer_text.append("  |  ", style="dim")
        footer_text.append(f"{hours:02d}:{minutes:02d}:{seconds:02d}", style="dim")
        footer_text.append("  |  ", style="dim")
        footer_text.append(f"Updates:{updates_str}", style="dim")

        return Panel(footer_text, style="blue", height=3)

    def _make_prices_panel(self) -> Panel:
        """Create prominent live prices display in the center."""
        table = Table(
            show_header=True,
            header_style="bold white on blue",
            expand=True,
            box=None,
            padding=(0, 2),
        )

        table.add_column("MARKET", style="bold cyan", width=22)
        table.add_column("YES", justify="center", width=12)
        table.add_column("NO", justify="center", width=12)
        table.add_column("SUM", justify="center", width=10)
        table.add_column("SKEW", justify="center", width=8)
        table.add_column("SIGNAL", justify="center", width=16)

        with self.price_lock:
            if not self.prices:
                table.add_row(
                    "[dim]Waiting for data...[/]",
                    "", "", "", "", ""
                )
            else:
                sorted_markets = sorted(
                    self.prices.items(),
                    key=lambda x: x[1].get("name", ""),
                )

                for market_id, data in sorted_markets:
                    name = data.get("name", market_id[:20])
                    up = data.get("up", 0)
                    down = data.get("down", 0)
                    sum_price = data.get("sum", 0)
                    skew = abs(up - down)
                    min_price = min(up, down)

                    # Determine signal based on skew strategy (use config values)
                    if skew >= config.ENTRY_MIN_SKEW and min_price <= config.ENTRY_MAX_CHEAP_PRICE:
                        if up <= down:
                            signal_text = "[bold green]BUY YES[/]"
                        else:
                            signal_text = "[bold red]BUY NO[/]"
                    else:
                        signal_text = "[dim]-[/]"

                    # Price styling
                    if sum_price < 0.98:
                        sum_style = "bold green"
                    elif sum_price < 1.02:
                        sum_style = "yellow"
                    else:
                        sum_style = "dim"

                    skew_style = "bold magenta" if skew >= config.ENTRY_MIN_SKEW else "dim"

                    table.add_row(
                        name,
                        Text(f"${up:.4f}", style="bold green"),
                        Text(f"${down:.4f}", style="bold red"),
                        Text(f"${sum_price:.4f}", style=sum_style),
                        Text(f"${skew:.2f}", style=skew_style),
                        signal_text,
                    )

        return Panel(
            table,
            title="[bold] LIVE MARKET PRICES [/]",
            border_style="cyan",
        )

    def _make_positions_table(self) -> Panel:
        """Create the positions table."""
        table = Table(
            title="Open Positions",
            show_header=True,
            header_style="bold magenta",
            expand=True,
        )

        table.add_column("Market", style="cyan", width=18)
        table.add_column("YES", justify="right", width=12)
        table.add_column("NO", justify="right", width=12)
        table.add_column("Pair$", justify="right", width=8)
        table.add_column("P&L/sh", justify="right", width=9)
        table.add_column("Status", justify="center", width=12)

        positions = self.position_tracker.positions

        if positions:
            for market_id, pos in positions.items():
                name = pos.market_name or market_id[:15]

                # YES position
                yes_text = f"{pos.qty_yes:.0f} @ ${pos.avg_yes:.2f}" if pos.qty_yes > 0 else "—"
                # NO position
                no_text = f"{pos.qty_no:.0f} @ ${pos.avg_no:.2f}" if pos.qty_no > 0 else "—"

                # Pair cost styling
                if pos.is_hedged:
                    if pos.pair_cost < 0.995:
                        pair_style = "bold green"
                    elif pos.pair_cost < 1.005:
                        pair_style = "yellow"
                    else:
                        pair_style = "red"
                    pair_text = Text(f"${pos.pair_cost:.3f}", style=pair_style)
                else:
                    pair_text = Text("—", style="dim")

                # Expected P&L per share (can be negative)
                if pos.is_hedged:
                    pnl = pos.expected_pnl
                    if pnl >= 0.005:  # +$0.005 or more
                        pnl_text = Text(f"+${pnl:.3f}", style="bold green")
                        status = "[green]PROFIT[/]"
                    elif pnl >= -0.005:  # Near breakeven
                        pnl_text = Text(f"${pnl:.3f}", style="yellow")
                        status = "[yellow]EVEN[/]"
                    elif pnl >= -0.02:  # Small loss (<2%)
                        pnl_text = Text(f"${pnl:.3f}", style="red")
                        status = "[red]LOSS[/]"
                    else:  # Larger loss
                        pnl_text = Text(f"${pnl:.3f}", style="bold red")
                        status = "[bold red]LOSS[/]"
                elif pos.qty_yes > 0 or pos.qty_no > 0:
                    pnl_text = Text("—", style="dim")
                    status = "[blue]UNHEDGED[/]"
                else:
                    pnl_text = Text("—", style="dim")
                    status = "[dim]EMPTY[/]"

                table.add_row(
                    name,
                    yes_text,
                    no_text,
                    pair_text,
                    pnl_text,
                    status,
                )
        else:
            table.add_row(
                "[dim]No positions yet[/]",
                "", "", "", "", ""
            )

        return Panel(table, border_style="green")

    def _make_summary_panel(self) -> Panel:
        """Create the summary statistics panel."""
        total_exposure = self.position_tracker.total_exposure()
        balance = self.executor.get_balance() if self.executor else 0
        trades = len(self.executor.orders) if self.executor else 0

        # Calculate total expected P&L
        total_pnl = sum(
            p.expected_pnl * p.hedged_qty
            for p in self.position_tracker.positions.values()
            if p.is_hedged
        )

        # Calculate exposure percentage
        exposure_pct = (total_exposure / self.max_exposure) * 100 if self.max_exposure > 0 else 0

        # Build summary text
        lines = []

        # Balance
        lines.append(f"[bold]Balance:[/] [cyan]${balance:.2f}[/]")

        # Exposure bar
        bar_width = 15
        filled = int((exposure_pct / 100) * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)
        exposure_color = "green" if exposure_pct < 70 else "yellow" if exposure_pct < 90 else "red"
        lines.append(
            f"[bold]Exposure:[/] [{exposure_color}]{bar}[/] ${total_exposure:.0f}"
        )

        # Expected P&L (can be negative)
        if total_pnl >= 0:
            pnl_style = "bold green"
            pnl_sign = "+"
        else:
            pnl_style = "red"
            pnl_sign = ""
        lines.append(f"[bold]Expected P&L:[/] [{pnl_style}]{pnl_sign}${total_pnl:.2f}[/]")

        # Trades
        lines.append(f"[bold]Trades:[/] {trades}")

        # Position counts
        positions = self.position_tracker.positions.values()
        hedged = len([p for p in positions if p.is_hedged])
        unhedged = len([p for p in positions if (p.qty_yes > 0 or p.qty_no > 0) and not p.is_hedged])
        lines.append(f"[bold]Hedged:[/] {hedged} | [bold]Open:[/] {unhedged}")

        return Panel(
            "\n".join(lines),
            title="Summary",
            border_style="yellow",
        )

    def _make_activity_panel(self) -> Panel:
        """Create the activity log panel."""
        if self.activity_log:
            content = "\n".join(self.activity_log)
        else:
            content = "[dim]No activity yet...[/]"

        return Panel(
            content,
            title="Recent Activity",
            border_style="magenta",
        )

    def _make_layout(self) -> Layout:
        """Create the full layout with prices at bottom."""
        layout = Layout()

        layout.split_column(
            Layout(name="top", ratio=1),
            Layout(name="prices", ratio=1),  # Prices at bottom (less flicker)
        )

        layout["top"].split_row(
            Layout(name="positions", ratio=2),
            Layout(name="sidebar", ratio=1),
        )

        layout["sidebar"].split_column(
            Layout(name="summary", ratio=1),
            Layout(name="activity", ratio=1),
        )

        # Populate
        layout["positions"].update(self._make_positions_table())
        layout["summary"].update(self._make_summary_panel())
        layout["activity"].update(self._make_activity_panel())
        layout["prices"].update(self._make_prices_panel())

        return layout

    def start(self):
        """Start the live TUI display."""
        self._running = True
        self._live = Live(
            self._make_layout(),
            console=self.console,
            refresh_per_second=2,
            screen=True,
            vertical_overflow="crop",
        )
        self._live.start()
        self.log_activity("[bold cyan]Trading bot started[/]")

    def update(self):
        """Update the display."""
        if self._live and self._running:
            self._live.update(self._make_layout())

    def stop(self):
        """Stop the live display."""
        self._running = False
        if self._live:
            self._live.stop()
            self._live = None

    def print_final_summary(self):
        """Print final summary after stopping."""
        self.console.print()
        self.console.rule("[bold blue]Final Trading Summary[/]")
        self.console.print()

        # Positions
        table = Table(title="Final Positions", show_header=True)
        table.add_column("Market")
        table.add_column("YES", justify="right")
        table.add_column("NO", justify="right")
        table.add_column("Pair Cost", justify="right")
        table.add_column("Profit", justify="right")

        for pos in self.position_tracker.positions.values():
            table.add_row(
                pos.market_name or pos.market_id[:20],
                f"{pos.qty_yes:.1f} @ ${pos.avg_yes:.3f}" if pos.qty_yes > 0 else "—",
                f"{pos.qty_no:.1f} @ ${pos.avg_no:.3f}" if pos.qty_no > 0 else "—",
                f"{pos.pair_cost:.4f}" if pos.is_hedged else "—",
                f"${pos.guaranteed_profit:.2f}" if pos.is_profitable else "—",
            )

        self.console.print(table)
        self.console.print()

        # Summary stats
        self.console.print(f"[bold]Total Exposure:[/] ${self.position_tracker.total_exposure():.2f}")
        self.console.print(f"[bold]Total Guaranteed Profit:[/] [green]${self.position_tracker.total_guaranteed_profit():.2f}[/]")
        self.console.print(f"[bold]Trades Executed:[/] {len(self.executor.orders) if self.executor else 0}")
        self.console.print(f"[bold]Final Balance:[/] ${self.executor.get_balance():.2f}" if self.executor else "")
        self.console.print()

"""Rich CLI dashboard — live status display."""
import time
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich.columns import Columns
from rich import box

from src.core.state_tracker import MarketStateTracker
from src.risk.risk_manager import RiskManager, RiskState


console = Console()


def render_dashboard(
    tracker: MarketStateTracker,
    risk: RiskManager,
    recent_signals: list,
    btc_price: float | None,
) -> Panel:
    state = risk.state

    # Stats panel
    stats = Table(box=box.SIMPLE, show_header=False)
    stats.add_column("Key", style="cyan")
    stats.add_column("Value", style="white")
    stats.add_row("BTC Price", f"${btc_price:,.2f}" if btc_price else "—")
    stats.add_row("Bankroll", f"${state.bankroll:,.2f}")
    stats.add_row("Daily PnL", f"${state.daily_pnl:+,.2f}")
    stats.add_row("Open Exposure", f"${state.open_exposure:.2f}")
    stats.add_row("Trades Today", str(state.trade_count))
    stats.add_row("Active Markets", str(tracker.active_count))
    stats.add_row("Status", "[red]HALTED[/red]" if state.halted else "[green]RUNNING[/green]")

    # Signals table
    sig_table = Table(title="Recent Signals", box=box.SIMPLE)
    sig_table.add_column("Market", style="dim")
    sig_table.add_column("TTE", justify="right")
    sig_table.add_column("Delta", justify="right")
    sig_table.add_column("Edge", justify="right")
    sig_table.add_column("Dir", justify="center")

    for sig in recent_signals[-10:]:
        color = "green" if sig.direction == "UP" else "red" if sig.direction == "DOWN" else "dim"
        sig_table.add_row(
            sig.market_id[:12],
            f"{sig.time_to_expiry:.1f}s",
            f"{sig.delta:+.2f}",
            f"{sig.edge * 100:.1f}%",
            f"[{color}]{sig.direction}[/{color}]",
        )

    return Panel(
        Columns([stats, sig_table]),
        title=f"[bold cyan]poly-oracle-edge[/bold cyan] — {time.strftime('%H:%M:%S')}",
        border_style="cyan",
    )

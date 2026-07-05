"""Edge computation, fractional-Kelly sizing, and hard risk limits.

All prices are probabilities in (0, 1) — i.e. dollars per $1-payout contract.
"""
from dataclasses import dataclass

from .kalshi_client import taker_fee_usd


@dataclass
class Decision:
    action: str          # "trade" | "skip"
    reason: str
    side: str = ""       # yes | no
    price: float = 0.0   # entry price (probability)
    contracts: int = 0
    cost_usd: float = 0.0
    fee_usd: float = 0.0
    edge_net: float = 0.0
    q_consensus: float = 0.0


def decide(q_claude: float, q_codex: float, yes_ask: float, no_ask: float, cfg: dict) -> Decision:
    # CODEX-B HIGH fix: a one-sided book (e.g. no_ask=0) previously reached Kelly
    # sizing and crashed on division by zero — reject invalid quotes up front.
    if not (0.0 < yes_ask < 1.0 and 0.0 < no_ask < 1.0):
        return Decision("skip", f"invalid quote (yes_ask={yes_ask}, no_ask={no_ask})")
    div = abs(q_claude - q_codex)
    if div > cfg["edge"]["consensus_max_divergence"]:
        return Decision("skip", f"model divergence {div:.2f} exceeds limit -> flag for human review")
    q = (q_claude + q_codex) / 2

    edge_yes = q - yes_ask - taker_fee_usd(yes_ask, 1)
    edge_no = (1 - q) - no_ask - taker_fee_usd(no_ask, 1)
    side, edge, price = (("yes", edge_yes, yes_ask) if edge_yes >= edge_no
                         else ("no", edge_no, no_ask))
    if edge < cfg["edge"]["min_edge_after_fees"]:
        return Decision("skip", f"net edge {edge:+.3f} below threshold "
                                f"{cfg['edge']['min_edge_after_fees']}", q_consensus=round(q, 4))

    q_side = q if side == "yes" else 1 - q
    p_eff = price + taker_fee_usd(price, 1)   # entry incl. per-contract fee
    kelly = (q_side - p_eff) / (1 - p_eff)
    stake = cfg["sizing"]["bankroll_usd"] * cfg["sizing"]["kelly_fraction"] * kelly
    stake = min(stake, cfg["risk"]["max_per_trade_usd"])
    contracts = int(stake // price)
    if contracts < 1:
        return Decision("skip", "kelly stake below one contract", q_consensus=round(q, 4))

    fee = taker_fee_usd(price, contracts)
    cost = round(contracts * price + fee, 2)
    # CODEX-B LOW fix: honor the Kelly stake on an ALL-IN basis (fees included),
    # not just the hard per-trade cap — floor stays at 1 contract when edge cleared.
    while contracts > 1 and (cost > cfg["risk"]["max_per_trade_usd"] or cost > stake + price):
        contracts -= 1
        fee = taker_fee_usd(price, contracts)
        cost = round(contracts * price + fee, 2)
    if cost > cfg["risk"]["max_per_trade_usd"]:
        return Decision("skip", "single contract exceeds per-trade cap", q_consensus=round(q, 4))

    return Decision("trade", "edge cleared", side, price, contracts,
                    cost, fee, round(edge, 4), round(q, 4))


@dataclass
class ExitPlan:
    exit_type: str          # "swing" | "hold"
    target_price: float     # side price at which to take profit (0 = none)
    stop_price: float       # side price at which to cut losses (0 = none)
    review_after_days: int  # re-judge with the ensemble after this many days held


def plan_exit(q_side: float, entry_price: float, cfg: dict) -> ExitPlan:
    """Assign an exit plan at entry. q_side/entry_price are for the held side.

    Take-profit captures a fraction of the entry->fair convergence; if there is
    too little room, the position is a hold-to-settlement. A lenient mechanical
    stop-loss backstops catastrophic moves; thesis breaks are caught by the
    periodic ensemble review, not a tight price stop.
    """
    sw = cfg.get("swing", {})
    review = int(sw.get("review_after_days", 5))
    stop = round(entry_price * sw.get("stop_loss_frac", 0.5), 4)
    if not sw.get("enabled", False):
        return ExitPlan("hold", 0.0, stop, review)
    gap = q_side - entry_price
    target = round(min(entry_price + sw.get("take_profit_capture", 0.6) * gap, 0.99), 4)
    if gap <= 0 or (target - entry_price) < sw.get("min_target_move", 0.03):
        return ExitPlan("hold", 0.0, stop, review)
    return ExitPlan("swing", target, stop, review)


def check_exit(target_price: float, stop_price: float, exit_bid: float) -> tuple[str | None, float]:
    """Mechanical exit test. exit_bid = current bid for the held side (sellable price)."""
    if target_price and exit_bid >= target_price:
        return "take_profit", exit_bid
    if stop_price and 0 < exit_bid <= stop_price:
        return "stop_loss", exit_bid
    return None, exit_bid


def check_risk(stats: dict, cost_usd: float, cfg: dict) -> str | None:
    """Hard limits. Returns a veto reason, or None if the order may proceed."""
    r = cfg["risk"]
    if stats["realized_pnl_today"] <= -r["daily_loss_halt_usd"]:
        return "daily loss circuit breaker tripped - halt for today"
    if stats["risk_used_today"] + cost_usd > r["max_daily_risk_usd"]:
        return "daily risk budget exhausted"
    if stats["open_exposure"] + cost_usd > r["max_total_exposure_usd"]:
        return "total exposure cap reached"
    if stats["open_positions"] >= r["max_open_positions"]:
        return "max open positions reached"
    return None

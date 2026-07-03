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
    while cost > cfg["risk"]["max_per_trade_usd"] and contracts > 1:
        contracts -= 1
        fee = taker_fee_usd(price, contracts)
        cost = round(contracts * price + fee, 2)

    return Decision("trade", "edge cleared", side, price, contracts,
                    cost, fee, round(edge, 4), round(q, 4))


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

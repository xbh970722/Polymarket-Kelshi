"""Offline paper-lane smoke for the D1 event book. NOT a test (never pytest).

Proves the code chain closes end-to-end with ZERO network, ZERO keys, ZERO live
import, and ZERO writes to the real data/events.db or data/ledger.db:

    strict research -> 1 paper position -> 1 mark -> 1 binary settlement -> report/NAV

Everything runs in a throwaway temp dir. `events.KalshiPublic` is swapped for a
synthetic in-memory market/order-book so no HTTP ever leaves the process. Run:

    python scripts/events_paper_smoke.py

Exit 0 = the whole state sequence formed and the production DBs are untouched.
"""
import datetime as dt
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import event_research  # noqa: E402
from src import events          # noqa: E402

TICKER = "KXSMOKE-26-A"
STATE = {"phase": "open"}       # open | mark | settled


def _iso(d):
    return d.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _raw_market(status, yb, ya, nb, na, result=None):
    close = _iso(dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3))
    return {
        "ticker": TICKER, "status": status, "result": result,
        "yes_bid_dollars": f"{yb}", "yes_ask_dollars": f"{ya}",
        "no_bid_dollars": f"{nb}", "no_ask_dollars": f"{na}",
        "last_price_dollars": f"{ya}", "volume_24h_fp": "1200",
        "open_interest_fp": "5000", "close_time": close,
        "title": "Smoke event resolves YES", "yes_sub_title": "YES",
        "rules_primary": "Resolves YES if the synthetic smoke condition holds.",
        "rules_secondary": "Settlement per the synthetic smoke source.",
    }


class FakePublic:
    """Synthetic public client: no sockets, phase-driven quotes + a deep book."""

    def __init__(self, *_a, **_k):
        pass

    def market(self, ticker):
        if STATE["phase"] == "settled":
            return _raw_market("settled", 0.0, 0.0, 0.0, 0.0, result="yes")
        if STATE["phase"] == "mark":
            return _raw_market("active", 0.40, 0.41, 0.59, 0.60)
        return _raw_market("active", 0.29, 0.30, 0.70, 0.71)

    def market_norm(self, ticker):
        from src.kalshi_client import normalize_market
        return normalize_market(self.market(ticker))

    def _get(self, path, **_params):
        # orderbook_fp holds BID arrays: no_dollars (YES buyers consume) at 0.70
        # -> YES cost 0.30; yes_dollars at 0.30 -> NO cost 0.70. Depth 100 each.
        if path.endswith("/orderbook"):
            return {"orderbook_fp": {"no_dollars": [["0.70", 100]],
                                     "yes_dollars": [["0.30", 100]]}}
        raise AssertionError(f"unexpected network path in smoke: {path}")


def _build_research(brief_loaded, scan_run_id):
    blind = brief_loaded[TICKER]["blind"]
    packet_sha = event_research.canonical_sha256(blind)
    rules_sha = event_research.canonical_sha256(
        {"rules_primary": blind.get("rules_primary"),
         "rules_secondary": blind.get("rules_secondary")})
    brief_sha = event_research.canonical_sha256(brief_loaded)
    now = dt.datetime.now(dt.timezone.utc)

    def est(eid, p):
        return {"estimator_id": eid, "family": eid.split("_")[0],
                "persona": "inside_view" if eid.endswith("inside") else "outside_view",
                "model": "smoke-model-v1", "blind_packet_sha256": packet_sha,
                "market_price_seen": False, "p_yes": p, "ci80": [0.45, 0.65],
                "key_drivers": ["s1"], "counterevidence": ["none"],
                "what_would_change_mind": ["condition"]}

    return {
        "schema": "d1-research-v2",
        "research_run_id": "smoke-run-0001",
        "created_at": _iso(now),
        "scan_run_id": scan_run_id,
        "brief_file": "data/events_brief.json",
        "brief_sha256": brief_sha,
        "producer": {"orchestrator": "ev-research-orchestrator",
                     "protocol": "research/PROTOCOL.md",
                     "ensemble_config_sha256": "0" * 64, "arbiter_model": "fable-5"},
        "items": [{
            "ticker": TICKER, "event_ticker": "KXSMOKE-26",
            "title": "Smoke event resolves YES", "category": "Politics",
            "category_override": None,
            "close_time": _iso(now + dt.timedelta(days=3)),
            "thesis_id": "smoke-event-before-deadline-v1",
            "causal_cluster_id": "smoke-cluster-2026",
            "asof": _iso(now),
            "blind_packet_sha256": packet_sha, "rules_sha256": rules_sha,
            "sources": [{"source_id": "s1", "url": "https://official.example/doc",
                         "tier": "S0", "published_at": _iso(now - dt.timedelta(hours=2)),
                         "retrieved_at": _iso(now - dt.timedelta(hours=1)),
                         "claim": "The smoke condition is on track.", "stance": "supports"}],
            "estimators": [est("opus_inside", 0.55), est("opus_outside", 0.55),
                           est("codex_inside", 0.55), est("codex_outside", 0.55)],
            "round2": {"required": False, "blind_voided": False,
                       "factual_basis_error": None, "opus": None, "codex": None},
            "q_all": [0.55, 0.55, 0.55, 0.55], "q_claude": 0.55, "q_codex": 0.55,
            "arbiter_market_snapshot": {"asof": _iso(now - dt.timedelta(minutes=2)),
                                        "yes_bid": 0.29, "yes_ask": 0.30,
                                        "no_bid": 0.70, "no_ask": 0.71},
            "arbiter": {"model": "fable-5", "blind_packet_sha256": packet_sha,
                        "rules_clear": True, "sources_fresh": True, "blind_integrity": True,
                        "round2_required": False, "veto": False, "trade_eligible": True,
                        "reason_codes": [], "cruxes": ["Does the condition hold?"],
                        "reason": "clean"},
            "recommended_action": "trade",
            "rationale": "Core case supported by S0; main risk noted; families agree.",
            "material_evidence_delta": False, "delta_note": "", "prior_research_sha256": None,
        }],
    }


def _fingerprint(p: Path):
    if not p.exists():
        return None
    return (p.stat().st_mtime_ns, p.stat().st_size,
            hashlib.sha256(p.read_bytes()).hexdigest())


def main() -> int:
    real_events = ROOT / "data" / "events.db"
    real_ledger = ROOT / "data" / "ledger.db"
    fp_events_before = _fingerprint(real_events)
    fp_ledger_before = _fingerprint(real_ledger)

    tmp = Path(tempfile.mkdtemp(prefix="d1_smoke_"))
    ok = True
    try:
        (tmp / "data").mkdir(parents=True, exist_ok=True)
        # redirect every events.py path into the temp sandbox
        events.DB = tmp / "data" / "events.db"
        events.SCAN_JSON = tmp / "data" / "events_scan.json"
        events.BRIEF_JSON = tmp / "data" / "events_brief.json"
        events.RESEARCH_DIR = tmp / "data" / "events_research"
        events.LEDGER_DB = tmp / "data" / "ledger.db"       # nonexistent -> no ledger read
        events.KalshiPublic = FakePublic                    # no network anywhere

        scan_run_id = "2026-07-10T00:00:00+00:00"
        scan = {"generated": scan_run_id, "scan_run_id": scan_run_id,
                "candidates": [{"ticker": TICKER, "event_ticker": "KXSMOKE-26",
                                "category": "Politics", "title": "Smoke event resolves YES",
                                "mid": 0.30}]}
        events.SCAN_JSON.write_text(json.dumps(scan, indent=2), encoding="utf-8")

        brief = {TICKER: {
            "blind": {"ticker": TICKER, "title": "Smoke event resolves YES",
                      "subtitle": "YES",
                      "rules_primary": "Resolves YES if the synthetic smoke condition holds.",
                      "rules_secondary": "Settlement per the synthetic smoke source.",
                      "close_time": _iso(dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3)),
                      "category": "Politics", "doctrine": "", "sibling_titles": []},
            "arbiter": {"yes_bid": 0.29, "yes_ask": 0.30, "mid": 0.295,
                        "volume_24h": 1200, "oi": 5000, "sibling_mids": [],
                        "mp_flags": [], "mp_score": 1.0}}}
        events.BRIEF_JSON.write_text(json.dumps(brief, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
        brief_loaded = json.loads(events.BRIEF_JSON.read_text(encoding="utf-8"))

        research = _build_research(brief_loaded, scan_run_id)
        research_path = tmp / "research.json"
        research_path.write_text(json.dumps(research, indent=2, ensure_ascii=False),
                                 encoding="utf-8")

        cfg = {}
        print("=== D1 EVENT PAPER SMOKE (offline, synthetic) ===")

        ok_v, errors = events.validate_research_file(cfg, str(research_path))
        print(f"[1] validate strict research: {'OK' if ok_v else 'FAIL'}")
        if not ok_v:
            for e in errors:
                print(f"      - {e}")
            return 1

        # state 0: no trades
        with events._conn() as c:
            n0 = c.execute("SELECT COUNT(*) n FROM paper_trades").fetchone()["n"]
        assert n0 == 0, "expected 0 paper trades at start"
        print(f"[2] pre-decide paper_trades = {n0}")

        # state 1: one open position
        STATE["phase"] = "open"
        events.decide_paper(cfg, str(research_path))
        with events._conn() as c:
            opens = c.execute("SELECT * FROM paper_trades WHERE status='open'").fetchall()
        assert len(opens) == 1, f"expected 1 open, got {len(opens)}"
        pos = opens[0]
        print(f"[3] 1 OPEN: {pos['side'].upper()} x{pos['contracts']} @ {pos['price']:.3f}"
              f" cost=${pos['cost_usd']:.2f} edge={pos['edge_net']:+.3f}"
              f" cluster={pos['causal_cluster_id']} run={pos['research_run_id']}")
        assert pos["cost_usd"] <= events._cfg(cfg)["paper"]["max_per_trade_usd"] + 1e-9
        assert pos["research_run_id"] and pos["brief_sha256"] and pos["blind_packet_sha256"]

        # archive written exactly once even before settlement
        arch = list(events.RESEARCH_DIR.glob("*.json"))
        print(f"[4] research archived: {len(arch)} file(s) -> {events.RESEARCH_DIR.name}/")
        assert len(arch) == 1

        # state 2: one mark + NAV snapshot (position still open)
        STATE["phase"] = "mark"
        ns, nm, _ = events.settle(cfg)
        with events._conn() as c:
            marks = c.execute("SELECT * FROM marks").fetchall()
            navs = c.execute("SELECT * FROM nav ORDER BY d").fetchall()
        assert nm == 1 and len(marks) == 1, f"expected 1 mark, got {nm}"
        assert len(navs) >= 1
        print(f"[5] 1 MARK: sellable_bid={marks[0]['sellable_bid']:.3f}"
              f" | NAV=${navs[-1]['nav']:.2f} mtm_net=${navs[-1]['mtm_value']:.2f}")

        # state 3: one binary settlement
        STATE["phase"] = "settled"
        ns, nm, pnl = events.settle(cfg)
        with events._conn() as c:
            settled = c.execute("SELECT * FROM paper_trades WHERE status='settled'").fetchall()
            navs = c.execute("SELECT * FROM nav ORDER BY d").fetchall()
        assert len(settled) == 1 and settled[0]["result"] == "yes"
        s = settled[0]
        expect_pnl = round(s["contracts"] * 1.0 - s["cost_usd"], 4)
        assert abs((s["pnl_usd"] or 0) - expect_pnl) < 1e-6, "settled P&L mismatch"
        print(f"[6] 1 SETTLED binary: result=yes side={s['side']} pnl=${s['pnl_usd']:+.2f}"
              f" (hand-calc {s['contracts']}*$1 - ${s['cost_usd']:.2f} = ${expect_pnl:+.2f})")
        print(f"[7] NAV snapshots = {len(navs)} | final NAV=${navs[-1]['nav']:.2f}")

        print("--- report ---")
        events.report(cfg)

        # ---- red-line proofs ----
        print("=== RED-LINE PROOF ===")
        assert "src.live" not in sys.modules, "live module was imported!"
        print("  - src.live NEVER imported                              OK")
        print("  - events.KalshiPublic replaced by FakePublic (no HTTP) OK")
        fp_events_after = _fingerprint(real_events)
        fp_ledger_after = _fingerprint(real_ledger)
        assert fp_events_after == fp_events_before, "real data/events.db changed!"
        assert fp_ledger_after == fp_ledger_before, "real data/ledger.db changed!"
        print(f"  - real data/events.db fingerprint unchanged            OK ({'absent' if fp_events_before is None else 'same'})")
        print(f"  - real data/ledger.db fingerprint unchanged            OK ({'absent' if fp_ledger_before is None else 'same'})")
        print(f"  - all writes confined to {tmp}")
        print("SMOKE PASS: 0 trades -> 1 open -> 1 mark -> 1 binary settlement -> NAV")
    except AssertionError as e:
        ok = False
        print(f"SMOKE FAIL: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())

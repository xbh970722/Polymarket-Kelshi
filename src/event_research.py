"""D1-EVENT research contract: template producer + strict schema validator.

PURE MODULE. It does no network I/O, opens no database, and imports none of
`ledger`, `live`, `pipeline`, `engine`, or any order client. `make_template`
reads only the two files it is handed; every other function is deterministic in
its arguments. This is the machine gate that stops any four numbers from
masquerading as four-model research: the whole `d1-research-v2` file is checked
before `events.decide_paper` is allowed to write a single paper row.

Canonical hashing (UTF-8 JSON, sort_keys, tight separators, ensure_ascii=False,
then SHA-256) binds each research file to the exact brief blind packet, the
rules text, and the current scan. Aggregation, the half-way market anchor, the
S0/S1 evidence floor and every timestamp are recomputed here, never trusted from
the file's own self-report.

Note on `brief_sha256`: the spec calls for "the SHA-256 of the current brief".
This module binds via the *canonical* hash of the parsed brief dict rather than
the raw on-disk bytes, so the check is immune to whitespace/line-ending drift
while still failing closed on any content change. `make_template` and
`validate_research` derive it identically, so they can never disagree.
"""
import datetime as dt
import hashlib
import json
import math
import uuid
from pathlib import Path

SCHEMA_NAME = "d1-research-v2"
ESTIMATOR_IDS = ("opus_inside", "opus_outside", "codex_inside", "codex_outside")
TIERS = ("S0", "S1", "S2", "S3")
CLOCK_SKEW_SEC = 300           # 5 min allowance for clock skew (spec 4.2.8)
_EPS = 1e-9
_AGG_EPS = 1e-6                # aggregation / anchor equality tolerance
ZERO_HASH = "0" * 64


# ---------------------------------------------------------------- helpers ----
def canonical_sha256(value) -> str:
    """Deterministic SHA-256 of any JSON value: UTF-8, sort_keys, tight
    separators, ensure_ascii=False. The single hashing convention for the lane."""
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _is_finite_prob(x) -> bool:
    """True iff x is a real, finite number in [0, 1] (bools are rejected)."""
    return (isinstance(x, (int, float)) and not isinstance(x, bool)
            and math.isfinite(x) and 0.0 <= x <= 1.0)


def _parse_utc(s):
    """Parse an ISO-8601 string into a tz-AWARE UTC datetime, or None when the
    value is missing, unparseable, or timezone-naive (naive is rejected)."""
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        d = dt.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        return None
    return d.astimezone(dt.timezone.utc)


def _is_hex64(x) -> bool:
    if not isinstance(x, str) or len(x) != 64:
        return False
    try:
        int(x, 16)
    except ValueError:
        return False
    return True


def _half_anchor_ok(prior: float, final: float, market_mid: float) -> bool:
    """Half-way anchor: a round-2 family final may not close more than half of
    the blind prior's distance to the market. Moving away from the market is
    always allowed. Trivially true when the prior already sits on the market."""
    dist_prior = abs(prior - market_mid)
    return abs(final - market_mid) >= 0.5 * dist_prior - _EPS


def _brief_tickers(brief: dict) -> set:
    return {t for t, v in brief.items()
            if isinstance(v, dict) and isinstance(v.get("blind"), dict)}


def family_outputs(item: dict):
    """Recompute (q_opus, q_codex, q_all) from the four blind estimators and any
    round-2 finals. `q_all` order is fixed: opus_inside, opus_outside,
    codex_inside, codex_outside. Assumes the item already passed validation."""
    est = {e.get("estimator_id"): e for e in (item.get("estimators") or [])
           if isinstance(e, dict)}

    def pv(eid):
        return (est.get(eid) or {}).get("p_yes")

    oi, oo, ci, co = pv("opus_inside"), pv("opus_outside"), pv("codex_inside"), pv("codex_outside")
    q_all = [oi, oo, ci, co]
    r2 = item.get("round2") or {}
    q_opus = r2["opus"]["final_p_yes"] if isinstance(r2.get("opus"), dict) else (oi + oo) / 2.0
    q_codex = r2["codex"]["final_p_yes"] if isinstance(r2.get("codex"), dict) else (ci + co) / 2.0
    return q_opus, q_codex, q_all


# --------------------------------------------------------------- template ----
def make_template(brief_path, scan_path, cfg: dict = None) -> dict:
    """Build a fill-in `d1-research-v2` skeleton covering EVERY brief ticker that
    has a blind packet. Structural fields (tickers, hashes, snapshot skeleton,
    estimator ids) are prefilled; the orchestrator fills p_yes/ci80/sources/
    thesis_id/arbiter bools/recommended_action. A raw template does NOT pass the
    validator (placeholders are null) and is not meant to."""
    brief_path = Path(brief_path)
    scan_path = Path(scan_path)
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    scan = {}
    if scan_path.exists():
        try:
            scan = json.loads(scan_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            scan = {}
    scan_meta = {c.get("ticker"): c for c in (scan.get("candidates") or [])}
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    now_iso = now.isoformat().replace("+00:00", "Z")

    items = []
    for ticker in _brief_tickers(brief):
        blind = brief[ticker]["blind"]
        arb = brief[ticker].get("arbiter") or {}
        packet_sha = canonical_sha256(blind)
        rules_sha = canonical_sha256({"rules_primary": blind.get("rules_primary"),
                                      "rules_secondary": blind.get("rules_secondary")})
        cand = scan_meta.get(ticker) or {}
        yb, ya = arb.get("yes_bid"), arb.get("yes_ask")
        estimators = [{
            "estimator_id": eid,
            "family": eid.split("_")[0],
            "persona": "inside_view" if eid.endswith("inside") else "outside_view",
            "model": "FILL-exact-model-version",
            "blind_packet_sha256": packet_sha,
            "market_price_seen": False,
            "p_yes": None,
            "ci80": [None, None],
            "key_drivers": [],
            "counterevidence": [],
            "what_would_change_mind": [],
        } for eid in ESTIMATOR_IDS]
        items.append({
            "ticker": ticker,
            "event_ticker": cand.get("event_ticker"),
            "title": blind.get("title"),
            "category": cand.get("category") or blind.get("category") or "",
            "category_override": None,
            "close_time": blind.get("close_time"),
            "thesis_id": "FILL-thesis-id",
            "causal_cluster_id": cand.get("event_ticker") or ticker,
            "asof": now_iso,
            "blind_packet_sha256": packet_sha,
            "rules_sha256": rules_sha,
            "sources": [],
            "estimators": estimators,
            "round2": {"required": False, "blind_voided": False,
                       "factual_basis_error": None, "opus": None, "codex": None},
            "q_all": [None, None, None, None],
            "q_claude": None,
            "q_codex": None,
            "arbiter_market_snapshot": {
                "asof": now_iso,
                "yes_bid": yb, "yes_ask": ya,
                "no_bid": round(1.0 - ya, 4) if isinstance(ya, (int, float)) else None,
                "no_ask": round(1.0 - yb, 4) if isinstance(yb, (int, float)) else None,
            },
            "arbiter": {
                "model": "fable-5", "blind_packet_sha256": packet_sha,
                "rules_clear": None, "sources_fresh": None, "blind_integrity": None,
                "round2_required": False, "veto": None, "trade_eligible": None,
                "reason_codes": [], "cruxes": [], "reason": "",
            },
            "recommended_action": "no_trade",
            "rationale": "",
            "material_evidence_delta": False,
            "delta_note": "",
            "prior_research_sha256": None,
        })
    items.sort(key=lambda it: it["ticker"] or "")

    ens_sha = ZERO_HASH
    ens = (cfg or {}).get("ensemble")
    if ens is not None:
        ens_sha = canonical_sha256(ens)
    return {
        "schema": SCHEMA_NAME,
        "research_run_id": str(uuid.uuid4()),
        "created_at": now_iso,
        "scan_run_id": scan.get("scan_run_id"),
        "brief_file": str(brief_path).replace("\\", "/"),
        "brief_sha256": canonical_sha256(brief),
        "producer": {
            "orchestrator": "ev-research-orchestrator",
            "protocol": "research/PROTOCOL.md",
            "ensemble_config_sha256": ens_sha,
            "arbiter_model": "fable-5",
        },
        "items": items,
    }


# -------------------------------------------------------------- validator ----
def validate_research(doc, brief, scan, cfg, now) -> list:
    """Full-file preflight. Returns a list of stable `field.path: reason` error
    strings (empty == valid). Pure and read-only: no network, no DB, no writes.
    A single error means the WHOLE file is rejected by the caller."""
    errs = []
    if not isinstance(doc, dict):
        return ["doc: not a JSON object"]
    if doc.get("schema") != SCHEMA_NAME:
        errs.append(f"schema: expected {SCHEMA_NAME!r}, got {doc.get('schema')!r}")
    for f in ("research_run_id", "created_at", "scan_run_id", "brief_file",
              "brief_sha256", "producer", "items"):
        if f not in doc:
            errs.append(f"{f}: missing required top-level field")

    if not isinstance(brief, dict) or not brief:
        errs.append("brief: empty or not an object")
        return errs
    brief_bad = [t for t, v in brief.items()
                 if not (isinstance(v, dict) and isinstance(v.get("blind"), dict))]
    if brief_bad:
        errs.append(f"brief: {len(brief_bad)} ticker(s) have fetch errors "
                    f"(e.g. {brief_bad[0]}); re-run events-brief before research")
    brief_tickers = _brief_tickers(brief)

    # scan binding
    if isinstance(scan, dict) and scan.get("scan_run_id") is not None:
        if doc.get("scan_run_id") != scan.get("scan_run_id"):
            errs.append(f"scan_run_id: {doc.get('scan_run_id')!r} does not match current "
                        f"scan {scan.get('scan_run_id')!r} (stale research)")
    else:
        errs.append("scan: current data/events_scan.json has no scan_run_id")

    # brief binding (canonical hash of the parsed brief)
    if doc.get("brief_sha256") != canonical_sha256(brief):
        errs.append("brief_sha256: does not match the current brief content")

    prod = doc.get("producer")
    if not isinstance(prod, dict):
        errs.append("producer: not an object")
    else:
        for pf in ("orchestrator", "protocol", "ensemble_config_sha256", "arbiter_model"):
            if not prod.get(pf):
                errs.append(f"producer.{pf}: missing")

    ca = _parse_utc(doc.get("created_at"))
    if ca is None:
        errs.append("created_at: not timezone-aware UTC ISO-8601")
    elif ca > now + dt.timedelta(seconds=CLOCK_SKEW_SEC):
        errs.append("created_at: is in the future beyond clock skew")

    items = doc.get("items")
    if not isinstance(items, list) or not items:
        errs.append("items: missing or empty")
        return errs

    counts = {}
    for item in items:
        tk = item.get("ticker") if isinstance(item, dict) else None
        counts[tk] = counts.get(tk, 0) + 1
    item_tickers = set(counts)
    missing = brief_tickers - item_tickers
    extra = {t for t in item_tickers - brief_tickers if t is not None}
    dups = {t for t, n in counts.items() if n > 1 and t is not None}
    if missing:
        errs.append(f"items: missing brief ticker(s): {sorted(missing)[:6]}")
    if extra:
        errs.append(f"items: ticker(s) not in current brief: {sorted(extra)[:6]}")
    if dups:
        errs.append(f"items: duplicate ticker(s): {sorted(dups)[:6]}")

    max_age_h = float((cfg.get("paper") or {}).get("research_max_age_hours", 24))
    file_sha = doc.get("_file_sha256")     # optional: set by caller for re-entry hash check
    cluster_trades = {}
    for i, item in enumerate(items):
        try:
            _validate_item(errs, i, item, brief, now, max_age_h, cluster_trades, file_sha)
        except Exception as e:             # noqa: BLE001 - never crash the preflight
            errs.append(f"items[{i}]: internal validation error ({type(e).__name__}: {e})")

    for cid, cnt in cluster_trades.items():
        if cnt > 1:
            errs.append(f"items: {cnt} trade actions share event/cluster {cid!r}; "
                        f"a file may express at most one trade per event/cluster")
    return errs


def _validate_item(errs, i, item, brief, now, max_age_h, cluster_trades, file_sha):
    if not isinstance(item, dict):
        errs.append(f"items[{i}]: not an object")
        return
    tk = item.get("ticker")
    p = f"items[{i}]({tk})" if tk else f"items[{i}]"

    for f in ("ticker", "event_ticker", "thesis_id", "causal_cluster_id", "asof",
              "close_time", "blind_packet_sha256", "rules_sha256", "recommended_action"):
        if not item.get(f):
            errs.append(f"{p}.{f}: missing")

    action = item.get("recommended_action")
    if action not in ("trade", "no_trade"):
        errs.append(f"{p}.recommended_action: must be 'trade' or 'no_trade', got {action!r}")

    blind = None
    bentry = brief.get(tk)
    if isinstance(bentry, dict) and isinstance(bentry.get("blind"), dict):
        blind = bentry["blind"]
    exp_packet = canonical_sha256(blind) if blind is not None else None
    if blind is not None:
        exp_rules = canonical_sha256({"rules_primary": blind.get("rules_primary"),
                                      "rules_secondary": blind.get("rules_secondary")})
        if item.get("blind_packet_sha256") != exp_packet:
            errs.append(f"{p}.blind_packet_sha256: does not match this ticker's brief blind packet")
        if item.get("rules_sha256") != exp_rules:
            errs.append(f"{p}.rules_sha256: does not match brief rules_primary/secondary")

    # ---- estimators ----
    ests = item.get("estimators")
    est_by_id = {}
    if not isinstance(ests, list):
        errs.append(f"{p}.estimators: not a list")
        ests = []
    else:
        for e in ests:
            if isinstance(e, dict):
                est_by_id[e.get("estimator_id")] = e
        want = set(ESTIMATOR_IDS)
        got = set(est_by_id)
        for miss in sorted(want - got):
            errs.append(f"{p}.estimators: missing {miss}")
        for xtra in sorted(str(x) for x in (got - want)):
            errs.append(f"{p}.estimators: unexpected estimator id {xtra!r}")
        if len([e for e in ests if isinstance(e, dict)]) != len(est_by_id):
            errs.append(f"{p}.estimators: duplicate estimator id(s)")
        for eid in ESTIMATOR_IDS:
            e = est_by_id.get(eid)
            if e is None:
                continue
            if e.get("market_price_seen") is not False:
                errs.append(f"{p}.estimators.{eid}.market_price_seen: must be false (blind breach)")
            py = e.get("p_yes")
            if not _is_finite_prob(py):
                errs.append(f"{p}.estimators.{eid}.p_yes: not a finite probability in [0,1]")
            ci = e.get("ci80")
            if not (isinstance(ci, list) and len(ci) == 2
                    and _is_finite_prob(ci[0]) and _is_finite_prob(ci[1]) and ci[0] <= ci[1]):
                errs.append(f"{p}.estimators.{eid}.ci80: must be [lo,hi] in [0,1] with lo<=hi")
            elif _is_finite_prob(py) and not (ci[0] <= py <= ci[1]):
                errs.append(f"{p}.estimators.{eid}.ci80: does not contain p_yes")
            if exp_packet is not None and e.get("blind_packet_sha256") != exp_packet:
                errs.append(f"{p}.estimators.{eid}.blind_packet_sha256: does not match brief blind packet")

    have_four = all(_is_finite_prob((est_by_id.get(eid) or {}).get("p_yes")) for eid in ESTIMATOR_IDS)

    # ---- market snapshot (for the half-way anchor) ----
    snap = item.get("arbiter_market_snapshot") or {}
    snap_t = _parse_utc(snap.get("asof")) if snap else None
    if snap and snap_t is None:
        errs.append(f"{p}.arbiter_market_snapshot.asof: not timezone-aware UTC")
    yb, ya = snap.get("yes_bid"), snap.get("yes_ask")
    market_mid = (yb + ya) / 2.0 if (_is_finite_prob(yb) and _is_finite_prob(ya)) else None

    # ---- aggregation + round-2 half-anchor ----
    r2 = item.get("round2") or {}
    if not isinstance(r2, dict):
        errs.append(f"{p}.round2: not an object")
        r2 = {}
    # blind_voided must be a real bool; the half-anchor exemption is granted ONLY
    # by (blind_voided is True) + a non-empty factual_basis_error. A truthy non-bool
    # (e.g. the string "false") therefore never opens the escape hatch (fail closed).
    voided = r2.get("blind_voided")
    if voided is not None and not isinstance(voided, bool):
        errs.append(f"{p}.round2.blind_voided: must be a boolean")
    fbe = str(r2.get("factual_basis_error") or "").strip()
    if voided is True and not fbe:
        errs.append(f"{p}.round2.blind_voided: true requires a non-empty factual_basis_error")
    anchor_exempt = (voided is True and bool(fbe))

    if have_four:
        oi = est_by_id["opus_inside"]["p_yes"]
        oo = est_by_id["opus_outside"]["p_yes"]
        ci = est_by_id["codex_inside"]["p_yes"]
        co = est_by_id["codex_outside"]["p_yes"]
        q_all = item.get("q_all")
        expect = [oi, oo, ci, co]
        if not (isinstance(q_all, list) and len(q_all) == 4 and all(_is_finite_prob(x) for x in q_all)):
            errs.append(f"{p}.q_all: must be four probabilities in [0,1]")
        elif any(abs(a - b) > _EPS for a, b in zip(q_all, expect)):
            errs.append(f"{p}.q_all: order must mirror "
                        f"[opus_inside,opus_outside,codex_inside,codex_outside]")
        means = {"opus": (oi + oo) / 2.0, "codex": (ci + co) / 2.0}
        for fam, qfield in (("opus", "q_claude"), ("codex", "q_codex")):
            mean_v = means[fam]
            qval = item.get(qfield)
            r2fam = r2.get(fam)
            if isinstance(r2fam, dict):
                for rk in ("prior_p_yes", "final_p_yes", "new_evidence_ids", "reason"):
                    if rk not in r2fam:
                        errs.append(f"{p}.round2.{fam}.{rk}: missing")
                prior = r2fam.get("prior_p_yes")
                final = r2fam.get("final_p_yes")
                if not _is_finite_prob(prior):
                    errs.append(f"{p}.round2.{fam}.prior_p_yes: not a probability")
                elif abs(prior - mean_v) > _AGG_EPS:
                    errs.append(f"{p}.round2.{fam}.prior_p_yes: must equal the blind "
                                f"{fam} mean {mean_v:.4f}")
                if not _is_finite_prob(final):
                    errs.append(f"{p}.round2.{fam}.final_p_yes: not a probability")
                else:
                    if not (_is_finite_prob(qval) and abs(qval - final) <= _AGG_EPS):
                        errs.append(f"{p}.{qfield}: must equal round2 {fam} final {final}")
                    # A revised final (moved off the blind prior) must be anchor-checked.
                    # Without snapshot prices the anchor is unverifiable -> fail CLOSED,
                    # never silently skip (that was the missing-snapshot short-circuit).
                    revised = _is_finite_prob(prior) and abs(final - prior) > _AGG_EPS
                    if not anchor_exempt and revised:
                        if market_mid is None:
                            errs.append(f"{p}.round2.{fam}: revised final needs an "
                                        f"arbiter_market_snapshot with prices to verify the anchor")
                        elif not _half_anchor_ok(prior, final, market_mid):
                            errs.append(f"{p}.round2.{fam}: closes >half the blind distance to "
                                        f"market without blind_voided+factual_basis_error")
            else:
                if not (_is_finite_prob(qval) and abs(qval - mean_v) <= _AGG_EPS):
                    errs.append(f"{p}.{qfield}: with no round2 must equal the mean of the "
                                f"{fam} blind estimators ({mean_v:.4f})")
    else:
        errs.append(f"{p}: aggregation not verifiable (estimator set incomplete)")

    # ---- timestamps ----
    asof = _parse_utc(item.get("asof"))
    if asof is None:
        errs.append(f"{p}.asof: not timezone-aware UTC")
    else:
        if asof > now + dt.timedelta(seconds=CLOCK_SKEW_SEC):
            errs.append(f"{p}.asof: in the future beyond clock skew")
        if (now - asof).total_seconds() > max_age_h * 3600 + CLOCK_SKEW_SEC:
            errs.append(f"{p}.asof: research age exceeds {max_age_h:g}h max")

    # ---- sources ----
    srcs = item.get("sources")
    if not isinstance(srcs, list):
        errs.append(f"{p}.sources: must be a list")
        srcs = []
    latest_src_t = None
    for j, s in enumerate(srcs):
        if not isinstance(s, dict):
            errs.append(f"{p}.sources[{j}]: not an object")
            continue
        if s.get("tier") not in TIERS:
            errs.append(f"{p}.sources[{j}].tier: must be one of {list(TIERS)}")
        for tf in ("published_at", "retrieved_at"):
            tv = _parse_utc(s.get(tf))
            if tv is None:
                errs.append(f"{p}.sources[{j}].{tf}: not timezone-aware UTC")
            elif latest_src_t is None or tv > latest_src_t:
                latest_src_t = tv
        for sf in ("source_id", "url", "claim", "stance"):
            if not s.get(sf):
                errs.append(f"{p}.sources[{j}].{sf}: missing")

    if asof is not None:
        newest = None
        for t in (latest_src_t, snap_t):
            if t is not None and (newest is None or t > newest):
                newest = t
        if newest is not None and asof < newest - dt.timedelta(seconds=CLOCK_SKEW_SEC):
            errs.append(f"{p}.asof: earlier than its newest source/snapshot (evidence from the future)")

    # ---- arbiter object ----
    arb = item.get("arbiter")
    if not isinstance(arb, dict):
        errs.append(f"{p}.arbiter: not an object")
        arb = {}
    elif exp_packet is not None and arb.get("blind_packet_sha256") != exp_packet:
        errs.append(f"{p}.arbiter.blind_packet_sha256: does not match brief blind packet")

    # ---- material-evidence-delta triple (structural completeness) ----
    if item.get("material_evidence_delta") is True:
        if not str(item.get("delta_note") or "").strip():
            errs.append(f"{p}.delta_note: required (non-empty) when material_evidence_delta is true")
        psha = item.get("prior_research_sha256")
        if not _is_hex64(psha):
            errs.append(f"{p}.prior_research_sha256: required 64-hex when material_evidence_delta is true")
        elif file_sha and psha == file_sha:
            errs.append(f"{p}.prior_research_sha256: must differ from this research file's own hash")

    # ---- trade-eligibility gate ----
    if action == "trade":
        if arb.get("veto") is not False:
            errs.append(f"{p}.arbiter.veto: must be false for a trade action")
        if arb.get("trade_eligible") is not True:
            errs.append(f"{p}.arbiter.trade_eligible: must be true for a trade action")
        for ib in ("rules_clear", "sources_fresh", "blind_integrity"):
            if arb.get(ib) is not True:
                errs.append(f"{p}.arbiter.{ib}: must be true for a trade action")
        tiers = [s.get("tier") for s in srcs if isinstance(s, dict)]
        if not any(t in ("S0", "S1") for t in tiers):
            errs.append(f"{p}: a trade requires >=1 S0/S1 source (key claim on S3 only must veto)")
        cid = item.get("causal_cluster_id") or item.get("event_ticker") or tk
        cluster_trades[cid] = cluster_trades.get(cid, 0) + 1

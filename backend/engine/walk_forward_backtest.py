"""
Zero-Lookahead Chronological Walk-Forward Validation Harness.
"""
from typing import Dict, List, Any, Optional
import numpy as np
import pandas as pd

from .seller_intelligence import OptionSellerIntelligenceEngine
from .ml_calibrator import OutcomeProbabilityCalibrator


class WalkForwardBacktester:
    def __init__(self, engine: Optional[OptionSellerIntelligenceEngine] = None):
        self.engine = engine or OptionSellerIntelligenceEngine()

    def _extract_features(self, report) -> Dict[str, float]:
        spot = report.spot_close
        atr = max(report.atr_14, 1.0)
        ce = report.primary_resistance
        pe = report.primary_support
        ce_oi_prev = max(ce["oi_observed"] - ce["chg_in_oi_observed"], 1)
        pe_oi_prev = max(pe["oi_observed"] - pe["chg_in_oi_observed"], 1)
        return {
            "corridor_to_atr_ratio": report.regime.corridor_to_atr_ratio,
            "triggered_rules_count": float(report.regime.triggered_rules_count),
            "atm_iv_pct": report.atm_iv_pct,
            "ce_sdi_zscore": ce["composite_sdi_zscore"],
            "pe_sdi_zscore": pe["composite_sdi_zscore"],
            "ce_oi_chg_pct": (ce["chg_in_oi_observed"] / ce_oi_prev) * 100.0,
            "pe_oi_chg_pct": (pe["chg_in_oi_observed"] / pe_oi_prev) * 100.0,
            "dist_to_ce_danger_atr": (ce["danger_spot_primary_calc"] - spot) / atr,
            "dist_to_pe_danger_atr": (spot - pe["danger_spot_primary_calc"]) / atr,
            "dte": float(report.dte),
        }

    def run(
        self,
        bhav_df: pd.DataFrame,
        participant_df: Optional[pd.DataFrame] = None,
        fovolt_map: Optional[Dict[str, float]] = None,
        warmup_sessions: int = 8,
    ) -> Dict[str, Any]:
        all_dates = sorted(bhav_df["trade_date"].unique())
        if len(all_dates) <= warmup_sessions + 1:
            raise ValueError(
                f"Need at least {warmup_sessions + 2} trading dates for walk-forward validation; got {len(all_dates)}."
            )

        calibrator = OutcomeProbabilityCalibrator(min_train_samples=6)
        hist_features: List[Dict[str, float]] = []
        hist_labels: List[int] = []
        daily_logs: List[Dict[str, Any]] = []

        for i in range(warmup_sessions, len(all_dates) - 1):
            as_of_date = all_dates[i]
            next_date = all_dates[i + 1]

            causal_bhav = bhav_df[bhav_df["trade_date"] <= as_of_date].copy()
            causal_part = (
                participant_df[participant_df["trade_date"] <= as_of_date].copy()
                if participant_df is not None and not participant_df.empty
                else None
            )

            if len(hist_labels) >= 6:
                calibrator.fit(pd.DataFrame(hist_features[:-1]), np.array(hist_labels[:-1]))

            report = self.engine.analyze(causal_bhav, causal_part, fovolt_map)
            feat = self._extract_features(report)
            ml_probs = calibrator.predict_probs(feat)

            next_bhav = bhav_df[
                (bhav_df["trade_date"] == next_date)
                & (bhav_df["expiry_date"] == report.expiry_date)
            ].copy()

            if next_bhav.empty:
                continue

            next_spot_close = float(next_bhav["spot_close"].iloc[0])
            ce_wall_strike = report.primary_resistance["strike"]
            pe_wall_strike = report.primary_support["strike"]

            ce_next_rows = next_bhav[(next_bhav["strike"] == ce_wall_strike) & (next_bhav["option_type"] == "CE")]
            pe_next_rows = next_bhav[(next_bhav["strike"] == pe_wall_strike) & (next_bhav["option_type"] == "PE")]

            ce_next_high = float(ce_next_rows["high_price"].iloc[0]) if not ce_next_rows.empty else 0.0
            ce_next_chg_oi = int(ce_next_rows["chg_in_oi"].iloc[0]) if not ce_next_rows.empty else 0
            pe_next_high = float(pe_next_rows["high_price"].iloc[0]) if not pe_next_rows.empty else 0
            pe_next_chg_oi = int(pe_next_rows["chg_in_oi"].iloc[0]) if not pe_next_rows.empty else 0

            ce_delta = max(abs(report.primary_resistance["delta"]), 0.25)
            pe_delta = max(abs(report.primary_support["delta"]), 0.25)
            est_spot_high = max(
                next_spot_close,
                report.spot_close + max(0.0, ce_next_high - report.primary_resistance["eod_premium_observed"]) / ce_delta,
            )
            est_spot_low = min(
                next_spot_close,
                report.spot_close - max(0.0, pe_next_high - report.primary_support["eod_premium_observed"]) / pe_delta,
            )

            ce_danger_spot = report.primary_resistance["danger_spot_primary_calc"]
            ce_danger_prem = report.primary_resistance["danger_premium_calc"]
            pe_danger_spot = report.primary_support["danger_spot_primary_calc"]
            pe_danger_prem = report.primary_support["danger_premium_calc"]

            res_tested = est_spot_high >= ce_wall_strike * 0.9985
            res_held = next_spot_close <= ce_wall_strike * 1.0015

            sup_tested = est_spot_low <= pe_wall_strike * 1.0015
            sup_held = next_spot_close >= pe_wall_strike * 0.9985

            ce_spot_breached = est_spot_high >= ce_danger_spot
            ce_dual_confirmed = ce_spot_breached and (ce_next_high >= ce_danger_prem)
            ce_actual_covering = ce_next_chg_oi < 0 and next_spot_close > ce_wall_strike

            pe_spot_breached = est_spot_low <= pe_danger_spot
            pe_dual_confirmed = pe_spot_breached and (pe_next_high >= pe_danger_prem)
            pe_actual_covering = pe_next_chg_oi < 0 and next_spot_close < pe_wall_strike

            false_breakout_filtered = (
                (ce_spot_breached and not ce_dual_confirmed and res_held)
                or (pe_spot_breached and not pe_dual_confirmed and sup_held)
            )

            remained_sideways = (next_spot_close >= pe_wall_strike) and (next_spot_close <= ce_wall_strike)

            if ce_actual_covering:
                outcome_label = 1
            elif pe_actual_covering:
                outcome_label = 2
            else:
                outcome_label = 0

            hist_features.append(feat)
            hist_labels.append(outcome_label)

            daily_logs.append({
                "as_of_date": as_of_date,
                "next_date": next_date,
                "spot_close": report.spot_close,
                "next_spot_close": next_spot_close,
                "predicted_support": pe_wall_strike,
                "predicted_resistance": ce_wall_strike,
                "regime_verdict": report.regime.verdict,
                "is_no_trade_flagged": report.regime.is_no_trade,
                "remained_sideways": remained_sideways,
                "res_tested": res_tested,
                "res_held": res_held,
                "sup_tested": sup_tested,
                "sup_held": sup_held,
                "ce_danger_spot": ce_danger_spot,
                "ce_dual_confirmed": ce_dual_confirmed,
                "ce_actual_covering": ce_actual_covering,
                "pe_danger_spot": pe_danger_spot,
                "pe_dual_confirmed": pe_dual_confirmed,
                "pe_actual_covering": pe_actual_covering,
                "false_breakout_filtered": false_breakout_filtered,
                "ml_prob_hold": ml_probs["prob_range_hold_pct"],
            })

        log_df = pd.DataFrame(daily_logs)
        n_days = len(log_df)
        if n_days == 0:
            return {"error": "Insufficient overlapping expiry sessions for backtest."}

        res_tested_df = log_df[log_df["res_tested"]]
        sup_tested_df = log_df[log_df["sup_tested"]]
        no_trade_df = log_df[log_df["is_no_trade_flagged"]]
        dual_trig_df = log_df[log_df["ce_dual_confirmed"] | log_df["pe_dual_confirmed"]]

        return {
            "total_out_of_sample_sessions": int(n_days),
            "resistance_hold_rate_pct": round(float(log_df["res_held"].mean() * 100.0), 1),
            "tested_resistance_hold_rate_pct": round(
                float(res_tested_df["res_held"].mean() * 100.0) if not res_tested_df.empty else 100.0, 1
            ),
            "support_hold_rate_pct": round(float(log_df["sup_held"].mean() * 100.0), 1),
            "tested_support_hold_rate_pct": round(
                float(sup_tested_df["sup_held"].mean() * 100.0) if not sup_tested_df.empty else 100.0, 1
            ),
            "danger_zone_triggered_sessions": int(len(dual_trig_df)),
            "confirmed_short_covering_accuracy_pct": (
                round(float((dual_trig_df["ce_actual_covering"] | dual_trig_df["pe_actual_covering"]).mean() * 100.0), 1)
                if not dual_trig_df.empty else None
            ),
            "confirmed_short_covering_accuracy_sample_count": int(len(dual_trig_df)),
            "false_breakouts_filtered_count": int(log_df["false_breakout_filtered"].sum()),
            "sideways_no_trade_flagged_sessions": int(len(no_trade_df)),
            "sideways_no_trade_precision_pct": round(
                float(no_trade_df["remained_sideways"].mean() * 100.0)
                if not no_trade_df.empty else float(log_df["remained_sideways"].mean() * 100.0),
                1,
            ),
            "overall_range_containment_pct": round(float(log_df["remained_sideways"].mean() * 100.0), 1),
            "daily_validation_log": daily_logs,
        }

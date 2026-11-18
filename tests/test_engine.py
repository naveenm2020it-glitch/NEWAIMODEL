import unittest
import pandas as pd
from backend.engine.ml_calibrator import OutcomeProbabilityCalibrator
from backend.engine import (
    NSEDataLoader,
    OptionSellerIntelligenceEngine,
    WalkForwardBacktester,
    bsm_price,
    implied_volatility,
    solve_spot_danger_level,
)


class TestSellerIntelligenceEngine(unittest.TestCase):
    def test_ml_probabilities_sum_to_100_when_a_class_is_missing(self):
        calibrator = OutcomeProbabilityCalibrator(min_train_samples=4)
        rows = []
        for i in range(8):
            rows.append({
                "corridor_to_atr_ratio": 1.0 + i * 0.1,
                "triggered_rules_count": float(i % 4),
                "atm_iv_pct": 12.0 + i,
                "ce_sdi_zscore": 0.2 * i,
                "pe_sdi_zscore": 0.15 * i,
                "ce_oi_chg_pct": float(i * 2),
                "pe_oi_chg_pct": float(i),
                "dist_to_ce_danger_atr": 0.5 + i * 0.1,
                "dist_to_pe_danger_atr": 0.6 + i * 0.1,
                "dte": float(2 + i),
            })
        calibrator.fit(pd.DataFrame(rows), __import__("numpy").array([0, 1, 0, 1, 0, 1, 0, 1]))
        probs = calibrator.predict_probs(rows[-1])
        self.assertAlmostEqual(
            probs["prob_range_hold_pct"] + probs["prob_ce_short_covering_pct"] + probs["prob_pe_short_covering_pct"],
            100.0,
            places=1,
        )
        self.assertEqual(probs["prob_pe_short_covering_pct"], 0.0)


    def test_calibrator_clears_stale_model_when_new_window_is_not_trainable(self):
        calibrator = OutcomeProbabilityCalibrator(min_train_samples=4)
        rows = [{
            "corridor_to_atr_ratio": 1.0 + i * 0.1,
            "triggered_rules_count": float(i % 4),
            "atm_iv_pct": 12.0 + i,
            "ce_sdi_zscore": 0.2 * i,
            "pe_sdi_zscore": 0.15 * i,
            "ce_oi_chg_pct": float(i * 2),
            "pe_oi_chg_pct": float(i),
            "dist_to_ce_danger_atr": 0.5 + i * 0.1,
            "dist_to_pe_danger_atr": 0.6 + i * 0.1,
            "dte": float(2 + i),
        } for i in range(8)]
        calibrator.fit(pd.DataFrame(rows), __import__("numpy").array([0, 1] * 4))
        self.assertTrue(calibrator.is_fitted)
        calibrator.fit(pd.DataFrame(rows[:3]), __import__("numpy").array([0, 1, 0]))
        self.assertFalse(calibrator.is_fitted)
        self.assertIsNone(calibrator.model)

    def test_calibrator_handles_missing_and_non_numeric_prediction_features(self):
        calibrator = OutcomeProbabilityCalibrator(min_train_samples=4)
        rows = [{
            "corridor_to_atr_ratio": 1.0 + i * 0.1,
            "triggered_rules_count": float(i % 4),
            "atm_iv_pct": 12.0 + i,
            "ce_sdi_zscore": 0.2 * i,
            "pe_sdi_zscore": 0.15 * i,
            "ce_oi_chg_pct": float(i * 2),
            "pe_oi_chg_pct": float(i),
            "dist_to_ce_danger_atr": 0.5 + i * 0.1,
            "dist_to_pe_danger_atr": 0.6 + i * 0.1,
            "dte": float(2 + i),
        } for i in range(8)]
        calibrator.fit(pd.DataFrame(rows), __import__("numpy").array([0, 1] * 4))
        probs = calibrator.predict_probs({"corridor_to_atr_ratio": "invalid", "dte": float("inf")})
        self.assertAlmostEqual(sum(probs.values()), 100.0, places=1)

    def test_participant_oi_parses_thousands_separators(self):
        participant = pd.DataFrame([
            {
                "trade_date": "2026-11-13",
                "Client Type": "FII",
                "Option Index Call Long": "1,200",
                "Option Index Call Short": "500",
                "Option Index Put Long": "300",
                "Option Index Put Short": "700",
            },
            {
                "trade_date": "2026-11-13",
                "Client Type": "Pro",
                "Option Index Call Long": "100",
                "Option Index Call Short": "50",
                "Option Index Put Long": "200",
                "Option Index Put Short": "100",
            },
        ])
        summary = OptionSellerIntelligenceEngine()._summarize_participants(
            participant, "2026-11-13"
        )
        self.assertEqual(summary["inst_net_call_contracts"], 750)
        self.assertEqual(summary["inst_net_put_contracts"], -300)

    def test_engine_rejects_empty_or_incomplete_bhavcopy_with_clear_error(self):
        engine = OptionSellerIntelligenceEngine()
        with self.assertRaisesRegex(ValueError, "Empty NSE Bhavcopy"):
            engine.analyze(pd.DataFrame())
        with self.assertRaisesRegex(ValueError, "missing required normalized columns"):
            engine.analyze(pd.DataFrame({"trade_date": ["2026-11-13"]}))

    def test_nse_iso_dates_are_not_reversed_by_dayfirst_parsing(self):
        values = pd.Series(["2026-11-13", "13-Nov-2026", "13/11/2026"])
        parsed = NSEDataLoader._parse_nse_date_series(values)
        self.assertEqual(parsed.dt.strftime("%Y-%m-%d").tolist(), [
            "2026-11-13", "2026-11-13", "2026-11-13"
        ])

    def test_engine_rejects_dataset_without_future_expiry(self):
        expired = pd.DataFrame({
            "trade_date": ["2026-11-18"],
            "expiry_date": ["2026-11-18"],
            "oi": [1000],
        })
        with self.assertRaisesRegex(ValueError, "No unexpired NIFTY option expiry"):
            OptionSellerIntelligenceEngine()._select_active_expiry(expired)

    def test_expired_only_option_chain_is_rejected(self):
        engine = OptionSellerIntelligenceEngine()
        expired = pd.DataFrame({
            "trade_date": ["2026-11-18"],
            "expiry_date": ["2026-11-17"],
            "oi": [1000],
        })
        with self.assertRaisesRegex(ValueError, "No unexpired NIFTY option expiry"):
            engine._select_active_expiry(expired)

    def test_bsm_iv_and_danger_inversion_roundtrip(self):
        F, K, T, sig = 25040.0, 25100.0, 5.0 / 252.0, 0.14
        prem = bsm_price(F, K, T, sig, "CE")
        solved_iv = implied_volatility(prem, F, K, T, "CE")
        self.assertAlmostEqual(solved_iv, sig, places=4)

        danger_prem = prem * 1.45
        s_danger = solve_spot_danger_level(danger_prem, K, 4.0 / 252.0, sig + 0.02, "CE", basis_spread=40.0)
        re_prem = bsm_price(s_danger + 40.0, K, 4.0 / 252.0, sig + 0.02, "CE")
        self.assertAlmostEqual(re_prem, danger_prem, delta=0.25)

    def test_eod_pipeline_and_walk_forward_backtest(self):
        loader = NSEDataLoader(symbol="NIFTY")
        bhav_df = loader.load_bhavcopy_directory("sample_data", max_sessions=30)
        # ISO UDiFF dates must remain month-first; dayfirst=True must not
        # shift ambiguous dates such as 2026-11-12 into December.
        self.assertIn("2026-11-12", set(bhav_df["trade_date"]))
        self.assertEqual(max(bhav_df["trade_date"]), "2026-11-13")
        part_df = loader.load_participant_oi_directory("sample_data")

        engine = OptionSellerIntelligenceEngine()
        report = engine.analyze(bhav_df, part_df)
        self.assertEqual(report.primary_resistance["strike"], 25100.0)
        self.assertEqual(report.primary_support["strike"], 24900.0)

        # Reordering the same EOD records must never change the selected walls.
        reversed_report = engine.analyze(bhav_df.iloc[::-1].reset_index(drop=True), part_df)
        self.assertEqual(reversed_report.primary_resistance["strike"], report.primary_resistance["strike"])
        self.assertEqual(reversed_report.major_resistance["strike"], report.major_resistance["strike"])
        self.assertEqual(reversed_report.primary_support["strike"], report.primary_support["strike"])
        self.assertEqual(reversed_report.major_support["strike"], report.major_support["strike"])

        # Regime output must always agree with the engine's documented 3-of-5 rule.
        self.assertEqual(report.regime.triggered_rules_count, len(report.regime.reasons))
        self.assertEqual(report.regime.total_rules, 5)
        self.assertEqual(report.regime.is_no_trade, report.regime.triggered_rules_count >= 3)

        bt = WalkForwardBacktester(engine)
        res = bt.run(bhav_df, part_df, warmup_sessions=8)
        self.assertGreaterEqual(res["total_out_of_sample_sessions"], 10)
        self.assertGreaterEqual(res["resistance_hold_rate_pct"], 70.0)


if __name__ == "__main__":
    unittest.main()

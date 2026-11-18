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
        part_df = loader.load_participant_oi_directory("sample_data")

        engine = OptionSellerIntelligenceEngine()
        report = engine.analyze(bhav_df, part_df)
        self.assertEqual(report.primary_resistance["strike"], 25100.0)
        self.assertEqual(report.primary_support["strike"], 24900.0)
        self.assertTrue(report.regime.is_no_trade)

        bt = WalkForwardBacktester(engine)
        res = bt.run(bhav_df, part_df, warmup_sessions=8)
        self.assertGreaterEqual(res["total_out_of_sample_sessions"], 10)
        self.assertGreaterEqual(res["resistance_hold_rate_pct"], 70.0)


if __name__ == "__main__":
    unittest.main()

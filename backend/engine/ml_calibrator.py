"""
Machine Learning Regime & Outcome Probability Calibrator.
"""
from typing import Dict
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier


class OutcomeProbabilityCalibrator:
    FEATURE_COLS = [
        "corridor_to_atr_ratio",
        "triggered_rules_count",
        "atm_iv_pct",
        "ce_sdi_zscore",
        "pe_sdi_zscore",
        "ce_oi_chg_pct",
        "pe_oi_chg_pct",
        "dist_to_ce_danger_atr",
        "dist_to_pe_danger_atr",
        "dte",
    ]

    def __init__(self, min_train_samples: int = 8):
        self.min_train_samples = min_train_samples
        self.model = None
        self.is_fitted = False

    def fit(self, X_df: pd.DataFrame, y: np.ndarray) -> None:
        if len(X_df) < self.min_train_samples or len(np.unique(y)) < 2:
            self.is_fitted = False
            return
        X = X_df[self.FEATURE_COLS].fillna(0.0).values
        clf = HistGradientBoostingClassifier(
            max_depth=3,
            learning_rate=0.05,
            max_iter=80,
            random_state=42,
        )
        clf.fit(X, y)
        self.model = clf
        self.is_fitted = True

    def predict_probs(self, feature_row: Dict[str, float]) -> Dict[str, float]:
        if not self.is_fitted or self.model is None:
            is_tight = feature_row.get("corridor_to_atr_ratio", 1.3) < 1.25
            hold_p = 66.0 if is_tight else 49.0
            rem = 100.0 - hold_p
            return {
                "prob_range_hold_pct": round(hold_p, 1),
                "prob_ce_short_covering_pct": round(rem * 0.52, 1),
                "prob_pe_short_covering_pct": round(rem * 0.48, 1),
            }

        X_in = np.array([[feature_row.get(c, 0.0) for c in self.FEATURE_COLS]])
        probs = self.model.predict_proba(X_in)[0]
        classes = list(self.model.classes_)
        prob_map = {int(cls): float(p) * 100.0 for cls, p in zip(classes, probs)}
        return {
            "prob_range_hold_pct": round(prob_map.get(0, 50.0), 1),
            "prob_ce_short_covering_pct": round(prob_map.get(1, 25.0), 1),
            "prob_pe_short_covering_pct": round(prob_map.get(2, 25.0), 1),
        }

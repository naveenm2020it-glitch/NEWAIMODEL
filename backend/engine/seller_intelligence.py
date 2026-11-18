"""
Core Option Seller Writing Intelligence & Next-Day Support/Resistance Engine.
Operates 100% from NSE End-of-Day (EOD) Bhavcopy, Participant OI, and FOVOLT files.
"""
import math
from typing import Dict, List, Optional, Any
import numpy as np
import pandas as pd

from .models import (
    ObservedStrikeEOD,
    EstimatedSellerPosition,
    CalculatedTriggerZones,
    StrikeIntelligenceRecord,
    OpeningGapContingency,
    SidewaysRegimeAssessment,
    NextDayIntelligenceReport,
)
from .bsm_greeks import (
    bsm_greeks,
    implied_volatility,
    solve_spot_danger_level,
)


class OptionSellerIntelligenceEngine:
    def __init__(
        self,
        tactical_window: int = 5,
        structural_window: int = 22,
        tactical_weight: float = 0.65,
        structural_weight: float = 0.35,
        strike_range_pct: float = 0.045,
        risk_free_rate: float = 0.065,
    ):
        self.tactical_window = tactical_window
        self.structural_window = structural_window
        self.tactical_weight = tactical_weight
        self.structural_weight = structural_weight
        self.strike_range_pct = strike_range_pct
        self.r = risk_free_rate

    def _compute_spot_atr_14(self, bhav_df: pd.DataFrame) -> float:
        daily_spots = (
            bhav_df.groupby("trade_date")["spot_close"]
            .first()
            .sort_index()
            .values
        )
        if len(daily_spots) < 2:
            return float(daily_spots[-1] * 0.0085) if len(daily_spots) == 1 else 200.0
        diffs = np.abs(np.diff(daily_spots))
        raw_atr = float(np.mean(diffs[-14:])) / 0.72
        return float(np.clip(raw_atr, daily_spots[-1] * 0.0045, daily_spots[-1] * 0.025))

    def _select_active_expiry(self, latest_df: pd.DataFrame) -> str:
        exp_oi = latest_df.groupby("expiry_date")["oi"].sum()
        as_of_dt = pd.to_datetime(latest_df["trade_date"].iloc[0])
        valid_exps = []
        for exp_str, total_oi in exp_oi.items():
            dte = (pd.to_datetime(exp_str) - as_of_dt).days
            if dte >= 1:
                valid_exps.append((exp_str, dte, total_oi))
        if not valid_exps:
            available = [str(value) for value in exp_oi.index.tolist()]
            raise ValueError(
                f"No unexpired NIFTY option expiry is available as of {as_of_dt.date()}. "
                f"Available expiry values: {available[:8]}"
            )
        max_oi = max(x[2] for x in valid_exps)
        liquid = [x for x in valid_exps if x[2] >= 0.35 * max_oi]
        if not liquid:
            raise ValueError("No sufficiently liquid future NIFTY expiry was found.")
        liquid.sort(key=lambda x: x[1])
        return liquid[0][0]

    def _summarize_participants(
        self, participant_df: Optional[pd.DataFrame], latest_date: str
    ) -> Dict[str, Any]:
        if participant_df is None or participant_df.empty:
            return {
                "available": False,
                "inst_net_call_contracts": 0,
                "inst_net_put_contracts": 0,
                "institutional_bias": "Neutral / Data Not Loaded",
                "pro_fii_call_short_dominant": True,
                "pro_fii_put_short_dominant": True,
            }

        dates = sorted(participant_df["trade_date"].unique())
        target_dt = latest_date if latest_date in dates else dates[-1]
        sub = participant_df[participant_df["trade_date"] == target_dt].copy()

        def get_net(client_types: List[str], long_kw: str, short_kw: str) -> int:
            rows = sub[sub["Client Type"].isin(client_types)]
            if rows.empty:
                return 0
            l_cols = [c for c in rows.columns if long_kw in c]
            s_cols = [c for c in rows.columns if short_kw in c]
            if not l_cols or not s_cols:
                return 0
            # Participant CSV exports may quote thousands separators
            # (for example, "1,200"). Strip grouping commas before numeric
            # conversion so valid positions are not silently counted as zero.
            long_raw = rows[l_cols[0]].astype("string").str.replace(",", "", regex=False).str.strip()
            short_raw = rows[s_cols[0]].astype("string").str.replace(",", "", regex=False).str.strip()
            long_val = pd.to_numeric(long_raw, errors="coerce").fillna(0).sum()
            short_val = pd.to_numeric(short_raw, errors="coerce").fillna(0).sum()
            return int(long_val - short_val)

        inst_net_call = get_net(["FII", "Pro"], "Option Index Call Long", "Option Index Call Short")
        inst_net_put = get_net(["FII", "Pro"], "Option Index Put Long", "Option Index Put Short")

        if inst_net_call < -25000 and inst_net_put < -25000:
            bias = "Dual Institutional Short Writing (Range/Theta Regime)"
        elif inst_net_call < -25000 and inst_net_put > 15000:
            bias = "Institutional Bearish / Call Writing + Put Hedging"
        elif inst_net_put < -25000 and inst_net_call > 15000:
            bias = "Institutional Bullish / Put Writing + Call Buying"
        else:
            bias = "Balanced / Tactical Institutional Positioning"

        return {
            "available": True,
            "as_of": target_dt,
            "inst_net_call_contracts": inst_net_call,
            "inst_net_put_contracts": inst_net_put,
            "institutional_bias": bias,
            "pro_fii_call_short_dominant": inst_net_call < 0,
            "pro_fii_put_short_dominant": inst_net_put < 0,
        }

    def analyze(
        self,
        bhav_df: pd.DataFrame,
        participant_df: Optional[pd.DataFrame] = None,
        fovolt_map: Optional[Dict[str, float]] = None,
        ml_probs: Optional[Dict[str, float]] = None,
    ) -> NextDayIntelligenceReport:
        required_columns = {
            "trade_date", "expiry_date", "strike", "option_type", "spot_close",
            "futures_close", "open_price", "high_price", "low_price",
            "close_price", "settle_price", "prev_close_price", "oi", "chg_in_oi",
            "volume", "turnover", "vwap", "lot_size", "oi_contracts",
            "chg_oi_contracts", "vol_contracts",
        }
        if bhav_df is None or bhav_df.empty:
            raise ValueError("Empty NSE Bhavcopy DataFrame provided.")
        missing_columns = sorted(required_columns.difference(bhav_df.columns))
        if missing_columns:
            raise ValueError(
                "NSE Bhavcopy is missing required normalized columns: "
                + ", ".join(missing_columns)
            )

        # Canonical row order makes calculations invariant to NSE CSV/import ordering.
        bhav_df = bhav_df.sort_values(
            ["trade_date", "expiry_date", "strike", "option_type"],
            ascending=[True, True, True, True],
            kind="mergesort",
        ).reset_index(drop=True)

        all_dates = sorted(bhav_df["trade_date"].dropna().astype(str).unique())
        if not all_dates:
            raise ValueError("NSE Bhavcopy contains no valid trade dates.")

        latest_date = all_dates[-1]
        window_22_dates = all_dates[-self.structural_window :]

        latest_all = bhav_df[bhav_df["trade_date"] == latest_date].copy()
        target_expiry = self._select_active_expiry(latest_all)

        as_of_dt = pd.to_datetime(latest_date)
        expiry_dt = pd.to_datetime(target_expiry)
        cal_days = max(1, (expiry_dt - as_of_dt).days)
        dte = max(1, int(round(cal_days * 5.0 / 7.0)))
        T_now = dte / 252.0
        T_next = max(0.35, dte - 1.0) / 252.0

        latest_exp = latest_all[latest_all["expiry_date"] == target_expiry].copy()
        spot_close = float(latest_exp["spot_close"].iloc[0])
        futures_close = float(latest_exp["futures_close"].iloc[0])
        basis_spread = futures_close - spot_close

        atr_14 = self._compute_spot_atr_14(bhav_df)
        nse_vol_pct = (
            float(fovolt_map[latest_date])
            if fovolt_map and latest_date in fovolt_map
            else round((atr_14 / spot_close) * math.sqrt(252.0) * 100.0, 2)
        )

        min_strike = spot_close * (1.0 - self.strike_range_pct)
        max_strike = spot_close * (1.0 + self.strike_range_pct)
        active_latest = latest_exp[
            (latest_exp["strike"] >= min_strike) & (latest_exp["strike"] <= max_strike)
        ].copy()
        if active_latest.empty:
            raise ValueError(
                f"No option strikes found within +/-{self.strike_range_pct * 100:.1f}% "
                f"of NIFTY spot ({spot_close:.2f}) for expiry {target_expiry}."
            )

        hist_22 = bhav_df[
            (bhav_df["trade_date"].isin(window_22_dates))
            & (bhav_df["strike"] >= min_strike)
            & (bhav_df["strike"] <= max_strike)
        ].copy()

        date_to_lag = {d: idx for idx, d in enumerate(reversed(window_22_dates))}
        hist_22["lag_j"] = hist_22["trade_date"].map(date_to_lag)
        hist_22["price_chg"] = hist_22["close_price"] - hist_22["prev_close_price"]

        part_summary = self._summarize_participants(participant_df, latest_date)

        prelim_records = []
        for _, row in active_latest.iterrows():
            K = float(row["strike"])
            opt_type = str(row["option_type"])
            close_p = float(row["close_price"])
            prev_p = float(row["prev_close_price"])
            price_chg = close_p - prev_p
            price_chg_pct = (price_chg / prev_p * 100.0) if prev_p > 0.05 else 0.0

            iv = implied_volatility(close_p, futures_close, K, T_now, opt_type, self.r)
            greeks = bsm_greeks(futures_close, K, T_now, iv, opt_type, self.r)

            obs = ObservedStrikeEOD(
                trade_date=latest_date,
                expiry_date=target_expiry,
                dte=dte,
                strike=K,
                option_type=opt_type,
                spot_close=spot_close,
                futures_close=futures_close,
                lot_size=int(row["lot_size"]),
                open_price=float(row["open_price"]),
                high_price=float(row["high_price"]),
                low_price=float(row["low_price"]),
                close_price=close_p,
                settle_price=float(row["settle_price"]),
                prev_close_price=prev_p,
                price_change=price_chg,
                price_change_pct=price_chg_pct,
                oi=int(row["oi"]),
                chg_in_oi=int(row["chg_in_oi"]),
                volume=int(row["volume"]),
                turnover=float(row["turnover"]) if pd.notna(row["turnover"]) else 0.0,
                vwap=float(row["vwap"]),
                oi_contracts=float(row["oi_contracts"]),
                chg_oi_contracts=float(row["chg_oi_contracts"]),
                vol_contracts=float(row["vol_contracts"]),
                iv=iv,
                delta=greeks["delta"],
                gamma=greeks["gamma"],
                theta=greeks["theta"],
                vega=greeks["vega"],
            )

            sub_hist = hist_22[
                (hist_22["strike"] == K) & (hist_22["option_type"] == opt_type)
            ].copy()
            sub_hist["is_target_exp"] = (sub_hist["expiry_date"] == target_expiry).astype(int)
            sub_hist.sort_values(
                ["lag_j", "is_target_exp", "oi", "chg_oi_contracts", "expiry_date", "close_price", "vwap"],
                ascending=[True, False, False, False, True, True, True],
                kind="mergesort",
                inplace=True,
            )
            sub_hist = sub_hist.drop_duplicates(subset=["lag_j"], keep="first")

            i5 = 0.0
            i22 = 0.0
            weighted_prices = []
            weighted_oi_adds = []
            weighted_decay_weights = []

            for _, hrow in sub_hist.iterrows():
                j = int(hrow["lag_j"])
                chg_oi_c = float(hrow["chg_oi_contracts"])
                vol_c = max(float(hrow["vol_contracts"]), 1.0)
                p_chg = float(hrow["price_chg"])

                if chg_oi_c > 0:
                    short_mult = 1.25 if p_chg <= 0 else 0.70
                    stickiness = 1.0 + min(chg_oi_c / vol_c, 1.0)
                    w_score = chg_oi_c * short_mult * stickiness

                    if j < self.tactical_window:
                        i5 += math.exp(-0.277 * j) * w_score
                    i22 += math.exp(-0.063 * j) * w_score

                    exp_weight = 1.5 if hrow["expiry_date"] == target_expiry else 0.5
                    rec_w = math.exp(-0.15 * j) * exp_weight
                    weighted_prices.append(float(hrow["vwap"]))
                    weighted_oi_adds.append(chg_oi_c)
                    weighted_decay_weights.append(rec_w)

            standing_oi_boost = obs.oi_contracts * 0.22
            i5_total = i5 + standing_oi_boost
            i22_total = i22 + standing_oi_boost * 1.4

            if weighted_prices:
                w_arr = np.array(weighted_decay_weights) * np.array(weighted_oi_adds)
                p_arr = np.array(weighted_prices)
                w_sum = float(np.sum(w_arr))
                p_mid = float(np.sum(w_arr * p_arr) / w_sum)
                p_var = float(np.sum(w_arr * ((p_arr - p_mid) ** 2)) / w_sum)
                p_std = math.sqrt(max(p_var, 0.0))
                half_band = max(0.75 * p_std, p_mid * 0.035)
                p_low = max(1.0, p_mid - half_band)
                p_high = p_mid + half_band
                rel_disp = p_std / max(p_mid, 1.0)
                conf_pct = float(np.clip(88.0 - rel_disp * 120.0 + min(len(weighted_prices) * 2.5, 10.0), 42.0, 94.0))
            else:
                p_mid = max(obs.vwap, obs.close_price)
                p_std = p_mid * 0.05
                p_low = max(1.0, p_mid * 0.95)
                p_high = p_mid * 1.05
                conf_pct = 45.0

            prelim_records.append({
                "obs": obs,
                "i5": i5_total,
                "i22": i22_total,
                "p_low": p_low,
                "p_mid": p_mid,
                "p_high": p_high,
                "p_std": p_std,
                "conf_pct": conf_pct,
            })

        i5_vals = np.array([r["i5"] for r in prelim_records])
        i22_vals = np.array([r["i22"] for r in prelim_records])
        i5_z = (i5_vals - np.mean(i5_vals)) / (np.std(i5_vals) + 1e-6)
        i22_z = (i22_vals - np.mean(i22_vals)) / (np.std(i22_vals) + 1e-6)
        sdi_scores = self.tactical_weight * i5_z + self.structural_weight * i22_z

        atm_records = sorted(prelim_records, key=lambda x: abs(x["obs"].strike - spot_close))
        atm_iv = float(np.mean([r["obs"].iv for r in atm_records[:2]])) if atm_records else 0.13

        dte_factor = np.clip(1.26 + 0.035 * min(dte, 7), 1.26, 1.50)
        iv_shock = float(np.clip(0.015 + 0.08 * atm_iv, 0.015, 0.032))

        full_records: List[StrikeIntelligenceRecord] = []
        for idx, item in enumerate(prelim_records):
            obs: ObservedStrikeEOD = item["obs"]
            sdi = float(sdi_scores[idx])
            pct_rank = float(np.mean(sdi_scores <= sdi) * 100.0)

            if pct_rank >= 80.0 and sdi > 0.45:
                conc_label = "High"
            elif pct_rank >= 50.0:
                conc_label = "Moderate"
            else:
                conc_label = "Low"

            prev_oi_est = max(obs.oi - obs.chg_in_oi, 1)
            oi_chg_pct = (obs.chg_in_oi / prev_oi_est) * 100.0
            capitulation_flag = bool(
                (oi_chg_pct <= -5.0)
                and (obs.close_price > item["p_high"])
                and (obs.price_change > 0)
            )

            if capitulation_flag:
                acc_status = "Capitulation / Short Covering"
            elif oi_chg_pct >= 5.0 and obs.price_change <= 0:
                acc_status = "Fresh Aggressive Accumulation"
            elif oi_chg_pct >= 2.0:
                acc_status = "Persistent Accumulation"
            elif oi_chg_pct <= -3.0:
                acc_status = "Partial Unwinding"
            else:
                acc_status = "Holding / Neutral"

            if obs.option_type == "CE":
                inst_align = "Pro/FII Aligned" if part_summary.get("pro_fii_call_short_dominant", True) else "Retail Heavy"
            else:
                inst_align = "Pro/FII Aligned" if part_summary.get("pro_fii_put_short_dominant", True) else "Retail Heavy"

            est = EstimatedSellerPosition(
                est_entry_low=item["p_low"],
                est_entry_mid=item["p_mid"],
                est_entry_high=item["p_high"],
                entry_dispersion=item["p_std"],
                estimation_confidence_pct=item["conf_pct"],
                intensity_5d=item["i5"],
                intensity_22d=item["i22"],
                composite_sdi_zscore=sdi,
                writing_concentration=conc_label,
                concentration_percentile=pct_rank,
                accumulation_status=acc_status,
                eod_capitulation_flag=capitulation_flag,
                institutional_alignment=inst_align,
            )

            be_prem = item["p_mid"]
            be_spot = (obs.strike + be_prem) if obs.option_type == "CE" else (obs.strike - be_prem)

            mtm_danger = item["p_high"] * dte_factor
            atr_danger = obs.close_price + abs(obs.delta) * (0.75 * atr_14) + 0.5 * obs.gamma * ((0.75 * atr_14) ** 2)
            danger_prem = max(mtm_danger, atr_danger, obs.close_price * 1.18)

            s_danger_low = solve_spot_danger_level(
                danger_prem * 0.96, obs.strike, T_next, obs.iv + iv_shock, obs.option_type, basis_spread, self.r
            )
            s_danger_primary = solve_spot_danger_level(
                danger_prem, obs.strike, T_next, obs.iv + iv_shock, obs.option_type, basis_spread, self.r
            )
            s_danger_high = solve_spot_danger_level(
                danger_prem * 1.05, obs.strike, T_next, obs.iv + iv_shock, obs.option_type, basis_spread, self.r
            )

            if obs.option_type == "PE":
                s_danger_low, s_danger_high = min(s_danger_low, s_danger_high), max(s_danger_low, s_danger_high)

            if capitulation_flag:
                role = "Vacated Breakout Vacuum"
                conf_rule = (
                    f"Sellers already covered EOD (OI {oi_chg_pct:.1f}%). "
                    f"Former wall at {int(obs.strike)} now acts as momentum flip zone."
                )
            elif obs.option_type == "CE":
                role = "Resistance / CE Trap Zone" if conc_label in ("High", "Moderate") else "Secondary CE Strike"
                conf_rule = (
                    f"15m Close: NIFTY Spot > {s_danger_primary:.1f} AND {int(obs.strike)} CE > Rs.{danger_prem:.1f}"
                )
            else:
                role = "Support / PE Trap Zone" if conc_label in ("High", "Moderate") else "Secondary PE Strike"
                conf_rule = (
                    f"15m Close: NIFTY Spot < {s_danger_primary:.1f} AND {int(obs.strike)} PE > Rs.{danger_prem:.1f}"
                )

            calc = CalculatedTriggerZones(
                seller_breakeven_premium=be_prem,
                seller_breakeven_spot=be_spot,
                danger_premium=danger_prem,
                danger_spot_low=s_danger_low,
                danger_spot_high=s_danger_high,
                danger_spot_primary=s_danger_primary,
                confirmation_rule=conf_rule,
                next_day_role=role,
            )

            full_records.append(
                StrikeIntelligenceRecord(
                    strike=obs.strike,
                    option_type=obs.option_type,
                    observed=obs,
                    estimated=est,
                    calculated=calc,
                )
            )

        ce_candidates = [
            r for r in full_records
            if r.option_type == "CE"
            and r.strike >= spot_close * 0.995
            and not r.estimated.eod_capitulation_flag
        ]
        ce_candidates.sort(
            key=lambda r: (
                -r.estimated.composite_sdi_zscore,
                -r.observed.chg_in_oi,
                -r.observed.oi,
                abs(r.strike - spot_close),
                r.strike,
            )
        )

        pe_candidates = [
            r for r in full_records
            if r.option_type == "PE"
            and r.strike <= spot_close * 1.005
            and not r.estimated.eod_capitulation_flag
        ]
        pe_candidates.sort(
            key=lambda r: (
                -r.estimated.composite_sdi_zscore,
                -r.observed.chg_in_oi,
                -r.observed.oi,
                abs(r.strike - spot_close),
                r.strike,
            )
        )

        if not ce_candidates:
            raise ValueError("No eligible CE resistance strikes found near/above NIFTY spot in the selected expiry.")
        if not pe_candidates:
            raise ValueError("No eligible PE support strikes found near/below NIFTY spot in the selected expiry.")

        # Keep strongest seller walls separate from nearby next-session levels.
        # "Nearby" is bounded by max(100 points, 0.75 x ATR14); a candidate
        # must also show moderate/high concentration, fresh OI addition, and non-rising premium.
        max_actionable_distance = max(100.0, 0.75 * atr_14)

        def qualified_nearby(record, side):
            distance = (record.strike - spot_close) if side == "CE" else (spot_close - record.strike)
            return (
                0 <= distance <= max_actionable_distance
                and record.estimated.writing_concentration != "Low"
                and record.observed.chg_in_oi > 0
                and record.observed.price_change <= 0
                and not record.estimated.eod_capitulation_flag
            )

        def distance_rank(record):
            return (
                abs(record.strike - spot_close),
                -record.estimated.composite_sdi_zscore,
                -record.observed.chg_in_oi,
                -record.observed.oi,
                record.strike,
            )

        nearby_ce = sorted([r for r in ce_candidates if qualified_nearby(r, "CE")], key=distance_rank)
        nearby_pe = sorted([r for r in pe_candidates if qualified_nearby(r, "PE")], key=distance_rank)
        strongest_ce = ce_candidates[0]
        strongest_pe = pe_candidates[0]
        primary_ce = nearby_ce[0] if nearby_ce else min(ce_candidates, key=distance_rank)
        primary_pe = nearby_pe[0] if nearby_pe else min(pe_candidates, key=distance_rank)

        major_ce = min(
            [r for r in ce_candidates if r.strike > primary_ce.strike],
            key=lambda r: (r.strike - primary_ce.strike, -r.estimated.composite_sdi_zscore),
            default=primary_ce,
        )
        major_pe = min(
            [r for r in pe_candidates if r.strike < primary_pe.strike],
            key=lambda r: (primary_pe.strike - r.strike, -r.estimated.composite_sdi_zscore),
            default=primary_pe,
        )

        primary_ce.calculated.next_day_role = "Nearest Resistance / CE Watch"
        if major_ce.strike != primary_ce.strike:
            major_ce.calculated.next_day_role = "Next Structural Resistance"
        primary_pe.calculated.next_day_role = "Nearest Support / PE Watch"
        if major_pe.strike != primary_pe.strike:
            major_pe.calculated.next_day_role = "Next Structural Support"

        def add_level_context(record, side, is_nearby):
            flat = record.to_flat_dict()
            distance = record.strike - spot_close if side == "CE" else spot_close - record.strike
            flat["distance_from_spot_pts"] = round(distance, 1)
            flat["within_actionable_range"] = bool(is_nearby)
            flat["selection_basis"] = (
                "NEAREST QUALIFIED SELLER WALL"
                if is_nearby else "NO NEARBY CONFIRMED WALL — NEAREST CANDIDATE ONLY"
            )
            return flat

        strongest_ce_flat = add_level_context(strongest_ce, "CE", False)
        strongest_pe_flat = add_level_context(strongest_pe, "PE", False)
        primary_ce_flat = add_level_context(primary_ce, "CE", bool(nearby_ce))
        primary_pe_flat = add_level_context(primary_pe, "PE", bool(nearby_pe))
        major_ce_flat = add_level_context(
            major_ce, "CE", bool(nearby_ce and qualified_nearby(major_ce, "CE"))
        )
        major_pe_flat = add_level_context(
            major_pe, "PE", bool(nearby_pe and qualified_nearby(major_pe, "PE"))
        )

        corridor_pts = max(0.0, primary_ce.strike - primary_pe.strike)
        corridor_atr_ratio = corridor_pts / max(atr_14, 1.0)
        reasons = []

        if not nearby_ce or not nearby_pe:
            missing_side = (
                "both CE and PE sides" if not nearby_ce and not nearby_pe
                else ("CE resistance side" if not nearby_ce else "PE support side")
            )
            reasons.append(
                f"NO TRADE GATE: No qualified nearby seller wall on {missing_side} "
                f"within {max_actionable_distance:.0f} points of spot. Distant strongest walls are context only."
            )

        if corridor_atr_ratio < 1.25:
            reasons.append(
                f"Tight Seller Corridor: {int(primary_pe.strike)} PE to {int(primary_ce.strike)} CE "
                f"is {corridor_pts:.0f} pts ({corridor_atr_ratio:.2f}x ATR14 < 1.25x threshold)."
            )
        if primary_ce.observed.chg_in_oi > 0 and primary_pe.observed.chg_in_oi > 0:
            reasons.append(
                f"Bilateral Seller Defense: Both {int(primary_ce.strike)} CE (+{primary_ce.observed.chg_in_oi:,} OI) "
                f"and {int(primary_pe.strike)} PE (+{primary_pe.observed.chg_in_oi:,} OI) added fresh shorts."
            )
        if primary_ce.observed.price_change < 0 and primary_pe.observed.price_change < 0:
            reasons.append(
                f"Theta Decay Dominance: Both primary CE ({primary_ce.observed.price_change:+.1f}) and "
                f"PE ({primary_pe.observed.price_change:+.1f}) lost premium into EOD."
            )
        vacated = [r for r in full_records if r.estimated.eod_capitulation_flag]
        if len(vacated) == 0:
            reasons.append("No EOD Short Covering: Zero strikes showed seller capitulation in latest session.")
        dist_to_ce_danger = max(0.0, primary_ce.calculated.danger_spot_primary - spot_close)
        dist_to_pe_danger = max(0.0, spot_close - primary_pe.calculated.danger_spot_primary)
        if min(dist_to_ce_danger, dist_to_pe_danger) > 0.65 * atr_14 and corridor_atr_ratio < 1.45:
            reasons.append(
                f"Insufficient Breakout Runway: Spot requires >{min(dist_to_ce_danger, dist_to_pe_danger):.0f} pts "
                f"just to reach seller danger levels inside a compressed range."
            )

        is_no_trade = len(reasons) >= 3 or not nearby_ce or not nearby_pe
        verdict = (
            "WAIT / NO TRADE — NO NEARBY CONFIRMED WALL"
            if is_no_trade and (not nearby_ce or not nearby_pe)
            else (
                "WAIT / NO TRADE — RANGE-BOUND PINNING REGIME"
                if is_no_trade
                else "ACTIONABLE — WATCH DUAL-PRICE TRIGGER LEVELS"
            )
        )

        regime = SidewaysRegimeAssessment(
            is_no_trade=is_no_trade,
            verdict=verdict,
            triggered_rules_count=len(reasons),
            total_rules=6,
            corridor_points=round(corridor_pts, 1),
            atr_14_points=round(atr_14, 1),
            corridor_to_atr_ratio=round(corridor_atr_ratio, 2),
            sideways_box_low=primary_pe.strike,
            sideways_box_high=primary_ce.strike,
            reasons=reasons,
        )

        flat_low = round(spot_close - 0.25 * atr_14, 1)
        flat_high = round(spot_close + 0.25 * atr_14, 1)
        gap_contingencies = [
            OpeningGapContingency(
                scenario="1. Flat / Inside-Range Open",
                open_spot_condition=f"9:15 AM NIFTY Spot opens between {flat_low} and {flat_high}",
                seller_impact="Both CE and PE sellers start with overnight theta cushion intact.",
                execution_rule=(
                    f"Enforce NO TRADE inside [{int(primary_pe.strike)} - {int(primary_ce.strike)}] unless a 15m candle "
                    f"closes above {primary_ce.calculated.danger_spot_primary:.1f} with {int(primary_ce.strike)} CE > Rs.{primary_ce.calculated.danger_premium:.1f} "
                    f"(or below {primary_pe.calculated.danger_spot_primary:.1f} with {int(primary_pe.strike)} PE > Rs.{primary_pe.calculated.danger_premium:.1f})."
                ),
            ),
            OpeningGapContingency(
                scenario="2. Gap-Up Open (CE Seller Stress)",
                open_spot_condition=f"9:15 AM NIFTY Spot opens above {primary_ce.calculated.seller_breakeven_spot:.1f}",
                seller_impact=f"{int(primary_ce.strike)} CE sellers open underwater on MTM against Est. Entry Rs.{primary_ce.estimated.est_entry_low:.1f}-{primary_ce.estimated.est_entry_high:.1f}.",
                execution_rule=(
                    f"Wait for 9:30 AM (1st 15m close): If {int(primary_ce.strike)} CE holds > Rs.{primary_ce.calculated.danger_premium:.1f} "
                    f"and Spot > {primary_ce.calculated.danger_spot_primary:.1f}, CE sellers are trapped -> Bullish Continuation toward {int(major_ce.strike)}. "
                    f"If CE drops back below Rs.{primary_ce.estimated.est_entry_high:.1f}, sellers defended -> Gap-Fill Fade."
                ),
            ),
            OpeningGapContingency(
                scenario="3. Gap-Down Open (PE Seller Stress)",
                open_spot_condition=f"9:15 AM NIFTY Spot opens below {primary_pe.calculated.seller_breakeven_spot:.1f}",
                seller_impact=f"{int(primary_pe.strike)} PE sellers open underwater on MTM against Est. Entry Rs.{primary_pe.estimated.est_entry_low:.1f}-{primary_pe.estimated.est_entry_high:.1f}.",
                execution_rule=(
                    f"Wait for 9:30 AM (1st 15m close): If {int(primary_pe.strike)} PE holds > Rs.{primary_pe.calculated.danger_premium:.1f} "
                    f"and Spot < {primary_pe.calculated.danger_spot_primary:.1f}, PE sellers are trapped -> Bearish Breakdown toward {int(major_pe.strike)}. "
                    f"If PE drops back below Rs.{primary_pe.estimated.est_entry_high:.1f}, sellers defended -> Gap-Fill Reversal."
                ),
            ),
        ]

        if not nearby_ce or not nearby_pe:
            gap_contingencies.insert(
                0,
                OpeningGapContingency(
                    scenario="NO TRADE — Nearby seller evidence missing",
                    open_spot_condition=(
                        "At least one side has no qualified seller wall within the configured spot-distance band."
                    ),
                    seller_impact="Distant strongest seller walls are context only, not immediate intraday levels.",
                    execution_rule=(
                        "Do not use these distant levels as option-buying entry signals. Wait for fresh intraday "
                        "structure and 5m/15m confirmation."
                    ),
                ),
            )

        default_probs = ml_probs or {
            "prob_range_hold_pct": round(68.0 if is_no_trade else 48.0, 1),
            "prob_ce_short_covering_pct": round(16.0 if is_no_trade else 27.0, 1),
            "prob_pe_short_covering_pct": round(16.0 if is_no_trade else 25.0, 1),
        }

        ce_danger_list = [r.to_flat_dict() for r in ce_candidates[:3]]
        pe_danger_list = [r.to_flat_dict() for r in pe_candidates[:3]]
        vacated_list = [r.to_flat_dict() for r in vacated]

        full_records.sort(key=lambda r: (r.strike, r.option_type))
        strike_table = [r.to_flat_dict() for r in full_records]

        return NextDayIntelligenceReport(
            as_of_date=latest_date,
            next_trading_hint="Next NSE Trading Session (Generated 100% from EOD Data)",
            expiry_date=target_expiry,
            dte=dte,
            spot_close=round(spot_close, 2),
            futures_close=round(futures_close, 2),
            atr_14=round(atr_14, 2),
            nse_eod_volatility_pct=round(nse_vol_pct, 2),
            atm_iv_pct=round(atm_iv * 100.0, 2),
            participant_summary=part_summary,
            regime=regime,
            primary_resistance=primary_ce_flat,
            major_resistance=major_ce_flat,
            primary_support=primary_pe_flat,
            major_support=major_pe_flat,
            strongest_resistance=strongest_ce_flat,
            strongest_support=strongest_pe_flat,
            actionability={
                "max_distance_points": round(max_actionable_distance, 1),
                "nearby_ce_count": len(nearby_ce),
                "nearby_pe_count": len(nearby_pe),
                "has_nearby_ce": bool(nearby_ce),
                "has_nearby_pe": bool(nearby_pe),
                "status": (
                    "NEARBY WALLS FOUND — WAIT FOR INTRADAY CONFIRMATION"
                    if nearby_ce and nearby_pe
                    else "NO TRADE — NO QUALIFIED NEARBY WALL"
                ),
            },
            ce_danger_zones=ce_danger_list,
            pe_danger_zones=pe_danger_list,
            vacated_capitulation_strikes=vacated_list,
            gap_contingencies=gap_contingencies,
            strike_table=strike_table,
            ml_outcome_probabilities=default_probs,
        )

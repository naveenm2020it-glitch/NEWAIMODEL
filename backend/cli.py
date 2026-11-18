"""
Command-Line Interface for 100% EOD NIFTY Option Seller Intelligence & Walk-Forward Validation.
Usage:
  python -m backend.cli --data-dir sample_data --output-dir outputs --backtest
"""
import argparse
import json
import os
import pandas as pd

from .engine import NSEDataLoader, OptionSellerIntelligenceEngine, WalkForwardBacktester


def format_markdown_brief(report) -> str:
    r = report
    pr = r.primary_resistance
    mr = r.major_resistance
    ps = r.primary_support
    ms = r.major_support

    lines = [
        f"# NIFTY Option Seller Intelligence Report (As of EOD {r.as_of_date})",
        "",
        f"- **Target Expiry**: `{r.expiry_date}` ({r.dte} Trading DTE)",
        f"- **NIFTY Spot Close (Observed)**: `{r.spot_close:,.2f}` | **Futures Close**: `{r.futures_close:,.2f}`",
        f"- **14D Spot ATR**: `{r.atr_14:.1f} pts` | **ATM IV**: `{r.atm_iv_pct:.2f}%` | **NSE Vol**: `{r.nse_eod_volatility_pct:.2f}%`",
        f"- **Institutional Bias**: {r.participant_summary.get('institutional_bias', 'N/A')}",
        "",
        "## 1. Sideways / No-Trade Regime Verdict",
        f"- **Verdict**: **{r.regime.verdict}** ({r.regime.triggered_rules_count}/{r.regime.total_rules} trap rules triggered)",
        f"- **Defended Seller Corridor**: `{int(r.regime.sideways_box_low)} PE` to `{int(r.regime.sideways_box_high)} CE` ({r.regime.corridor_points:.0f} pts = {r.regime.corridor_to_atr_ratio:.2f}x ATR14)",
    ]
    for reason in r.regime.reasons:
        lines.append(f"  - {reason}")

    lines.extend([
        "",
        "## 2. Next-Day Defended Walls & Seller Danger Triggers",
        "| Role | Strike | EOD Prem (Obs) | Est Entry Zone (Est) | Danger Prem (Calc) | Danger Spot (Calc) | 15m Dual-Price Confirmation Rule |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        f"| **Major Resistance** | `{int(mr['strike'])} CE` | Rs.{mr['eod_premium_observed']} | Rs.{mr['est_entry_zone_low']}-{mr['est_entry_zone_high']} | **Rs.{mr['danger_premium_calc']}** | **{mr['danger_spot_primary_calc']}** | {mr['confirmation_rule']} |",
        f"| **Primary Resistance** | `{int(pr['strike'])} CE` | Rs.{pr['eod_premium_observed']} | Rs.{pr['est_entry_zone_low']}-{pr['est_entry_zone_high']} | **Rs.{pr['danger_premium_calc']}** | **{pr['danger_spot_primary_calc']}** | {pr['confirmation_rule']} |",
        f"| **Primary Support** | `{int(ps['strike'])} PE` | Rs.{ps['eod_premium_observed']} | Rs.{ps['est_entry_zone_low']}-{ps['est_entry_zone_high']} | **Rs.{ps['danger_premium_calc']}** | **{ps['danger_spot_primary_calc']}** | {ps['confirmation_rule']} |",
        f"| **Major Support** | `{int(ms['strike'])} PE` | Rs.{ms['eod_premium_observed']} | Rs.{ms['est_entry_zone_low']}-{ms['est_entry_zone_high']} | **Rs.{ms['danger_premium_calc']}** | **{ms['danger_spot_primary_calc']}** | {ms['confirmation_rule']} |",
        "",
        "## 3. 9:15 AM Opening Gap Contingency Matrix (Zero Pre-Market Feed Needed)",
    ])
    for g in r.gap_contingencies:
        lines.extend([
            f"### {g.scenario}",
            f"- **Condition**: {g.open_spot_condition}",
            f"- **Seller MTM Impact**: {g.seller_impact}",
            f"- **Execution Rule**: {g.execution_rule}",
            "",
        ])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="NIFTY EOD Option Seller Intelligence CLI")
    parser.add_argument("--data-dir", default="sample_data", help="Directory containing NSE EOD CSVs")
    parser.add_argument("--output-dir", default="outputs", help="Directory for generated reports")
    parser.add_argument("--backtest", action="store_true", help="Run walk-forward validation")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    loader = NSEDataLoader(symbol="NIFTY")
    bhav_df = loader.load_bhavcopy_directory(args.data_dir, max_sessions=35)
    part_df = loader.load_participant_oi_directory(args.data_dir)
    fovolt_map = loader.load_fovolt_directory(args.data_dir)

    engine = OptionSellerIntelligenceEngine()
    report = engine.analyze(bhav_df, part_df, fovolt_map)

    json_path = os.path.join(args.output_dir, f"next_day_report_{report.as_of_date}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2)

    csv_path = os.path.join(args.output_dir, f"strike_intelligence_{report.as_of_date}.csv")
    pd.DataFrame(report.strike_table).to_csv(csv_path, index=False)

    md_path = os.path.join(args.output_dir, f"next_day_brief_{report.as_of_date}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(format_markdown_brief(report))

    print(f"[OK] Generated Next-Day Report as of EOD {report.as_of_date}")
    print(f"     Regime Verdict     : {report.regime.verdict}")
    print(f"     Primary Resistance : {int(report.primary_resistance['strike'])} CE (Danger Spot: {report.primary_resistance['danger_spot_primary_calc']}, Danger Prem: Rs.{report.primary_resistance['danger_premium_calc']})")
    print(f"     Primary Support    : {int(report.primary_support['strike'])} PE (Danger Spot: {report.primary_support['danger_spot_primary_calc']}, Danger Prem: Rs.{report.primary_support['danger_premium_calc']})")

    if args.backtest:
        bt = WalkForwardBacktester(engine)
        bt_res = bt.run(bhav_df, part_df, fovolt_map, warmup_sessions=8)
        bt_path = os.path.join(args.output_dir, "walk_forward_validation.json")
        with open(bt_path, "w", encoding="utf-8") as f:
            json.dump(bt_res, f, indent=2)
        print(f"[OK] Walk-Forward Validation ({bt_res['total_out_of_sample_sessions']} OOS days):")
        print(f"     Resistance Hold Rate : {bt_res['resistance_hold_rate_pct']}%")
        print(f"     Support Hold Rate    : {bt_res['support_hold_rate_pct']}%")
        print(f"     No-Trade Precision   : {bt_res['sideways_no_trade_precision_pct']}%")


if __name__ == "__main__":
    main()

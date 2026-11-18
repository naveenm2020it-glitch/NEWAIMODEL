# NIFTY Option Seller Intelligence Report (As of EOD 2026-11-13)

- **Target Expiry**: `2026-11-26` (9 Trading DTE)
- **NIFTY Spot Close (Observed)**: `25,005.00` | **Futures Close**: `25,045.00`
- **14D Spot ATR**: `112.5 pts` | **ATM IV**: `11.79%` | **NSE Vol**: `7.14%`
- **Institutional Bias**: Dual Institutional Short Writing (Range/Theta Regime)

## 1. Sideways / No-Trade Regime Verdict
- **Verdict**: **WAIT / NO TRADE — RANGE-BOUND PINNING REGIME** (3/5 trap rules triggered)
- **Defended Seller Corridor**: `24900 PE` to `25100 CE` (200 pts = 1.78x ATR14)
  - Bilateral Seller Defense: Both 25100 CE (+447,000 OI) and 24900 PE (+447,000 OI) added fresh shorts.
  - Theta Decay Dominance: Both primary CE (-22.7) and PE (-5.5) lost premium into EOD.
  - No EOD Short Covering: Zero strikes showed seller capitulation in latest session.

## 2. Next-Day Defended Walls & Seller Danger Triggers
| Role | Strike | EOD Prem (Obs) | Est Entry Zone (Est) | Danger Prem (Calc) | Danger Spot (Calc) | 15m Dual-Price Confirmation Rule |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Major Resistance** | `25200 CE` | Rs.156.31 | Rs.182.66-250.87 | **Rs.376.3** | **25370.45** | 15m Close: NIFTY Spot > 25370.4 AND 25200 CE > Rs.376.3 |
| **Primary Resistance** | `25100 CE` | Rs.197.15 | Rs.223.67-292.17 | **Rs.438.26** | **25367.56** | 15m Close: NIFTY Spot > 25367.6 AND 25100 CE > Rs.438.3 |
| **Primary Support** | `24900 PE` | Rs.157.85 | Rs.177.14-250.49 | **Rs.375.73** | **24640.99** | 15m Close: NIFTY Spot < 24641.0 AND 24900 PE > Rs.375.7 |
| **Major Support** | `24800 PE` | Rs.122.28 | Rs.141.29-213.05 | **Rs.319.58** | **24634.68** | 15m Close: NIFTY Spot < 24634.7 AND 24800 PE > Rs.319.6 |

## 3. 9:15 AM Opening Gap Contingency Matrix (Zero Pre-Market Feed Needed)
### 1. Flat / Inside-Range Open
- **Condition**: 9:15 AM NIFTY Spot opens between 24976.9 and 25033.1
- **Seller MTM Impact**: Both CE and PE sellers start with overnight theta cushion intact.
- **Execution Rule**: Enforce NO TRADE inside [24900 - 25100] unless a 15m candle closes above 25367.6 with 25100 CE > Rs.438.3 (or below 24641.0 with 24900 PE > Rs.375.7).

### 2. Gap-Up Open (CE Seller Stress)
- **Condition**: 9:15 AM NIFTY Spot opens above 25357.9
- **Seller MTM Impact**: 25100 CE sellers open underwater on MTM against Est. Entry Rs.223.7-292.2.
- **Execution Rule**: Wait for 9:30 AM (1st 15m close): If 25100 CE holds > Rs.438.3 and Spot > 25367.6, CE sellers are trapped -> Bullish Continuation toward 25200. If CE drops back below Rs.292.2, sellers defended -> Gap-Fill Fade.

### 3. Gap-Down Open (PE Seller Stress)
- **Condition**: 9:15 AM NIFTY Spot opens below 24686.2
- **Seller MTM Impact**: 24900 PE sellers open underwater on MTM against Est. Entry Rs.177.1-250.5.
- **Execution Rule**: Wait for 9:30 AM (1st 15m close): If 24900 PE holds > Rs.375.7 and Spot < 24641.0, PE sellers are trapped -> Bearish Breakdown toward 24800. If PE drops back below Rs.250.5, sellers defended -> Gap-Fill Reversal.

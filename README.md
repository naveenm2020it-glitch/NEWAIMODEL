# NIFTY Option Seller Writing Intelligence & Next-Day S/R Engine (100% EOD-Only + Standalone Android APK)

An institutional-grade Option Seller Writing Intelligence Engine that studies trailing **5-session** and **22-session** NSE End-of-Day (EOD) option chain reports to predict next-day support/resistance, seller entry bands, BSM-inverted spot danger levels, sideways/no-trade trap zones, and 9:15 AM opening gap contingency rules—with **zero pre-market or live market feed required**.

## Key Capabilities
1. **Strict Observed vs. Estimated vs. Calculated Separation**:
   - **Observed EOD Telemetry**: Strike, CE/PE, DTE, Spot & Futures Close, OHLC, Settlement, Previous Close, $\Delta P$, OI, $\Delta\text{OI}$, Volume, VWAP, BSM Implied Volatility, and Greeks ($\Delta, \Gamma, \Theta, \nu$).
   - **Estimated Seller Positioning**: $\Delta\text{OI}$-weighted estimated seller entry premium zone ($\hat{P}_{\text{low}} - \hat{P}_{\text{high}}$), Estimation Confidence %, 5D Tactical vs. 22D Structural Writing Intensity, Composite SDI Z-Score, Seller Accumulation/Unwinding Status, and EOD Capitulation Flags.
   - **Calculated Risk Triggers**: Seller Breakeven Spot, Danger Premium ($P_{\text{danger}}$), BSM-inverted Spot Danger Level ($S_{\text{danger}}$) under IV expansion shock, and Synchronized 15m Dual-Price Confirmation Rules.
2. **Sideways / No-Trade Trap Filter**: Evaluates 5 structural pinning conditions and issues a mandatory `WAIT / NO TRADE` warning before choppy sessions.
3. **Opening Gap Contingency Matrix**: Pre-computes exact 9:15 AM Flat, Gap-Up, and Gap-Down execution rules without needing a pre-market connection.
4. **Dual Runtime**:
   - **Standalone Offline Android APK** (`mobile_app/` + Capacitor 8) with rolling 25-session local WebView storage.
   - **Python EOD Engine, CLI & Walk-Forward Backtester** (`backend/`).

## Quick Start (Python Backend & Backtester)
```bash
pip install -r requirements.txt
python -m backend.cli --data-dir sample_data --output-dir outputs --backtest
```

## Quick Start (Standalone Android APK)
See `BUILD_APK_GUIDE.md` for step-by-step commands to compile `app-debug.apk` or a signed release `.apk`.

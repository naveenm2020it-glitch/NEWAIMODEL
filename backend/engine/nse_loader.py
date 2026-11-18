"""
NSE EOD Report Ingestion & Normalization Layer.
Supports F&O UDiFF Bhavcopy (.csv/.zip), Participant-Wise OI CSV, and FOVOLT CSV.
"""
import os
import glob
import zipfile
from typing import Dict
import numpy as np
import pandas as pd


class NSEDataLoader:
    BHAV_COL_MAP = {
        "TradDt": "trade_date",
        "TIMESTAMP": "trade_date",
        "FinInstrmTp": "instrument_type",
        "INSTRUMENT": "instrument_type",
        "TckrSymb": "symbol",
        "SYMBOL": "symbol",
        "XpryDt": "expiry_date",
        "EXPIRY_DT": "expiry_date",
        "StrkPric": "strike",
        "STRIKE_PR": "strike",
        "OptnTp": "option_type",
        "OPTION_TYP": "option_type",
        "OpnPric": "open_price",
        "OPEN": "open_price",
        "HghPric": "high_price",
        "HIGH": "high_price",
        "LwPric": "low_price",
        "LOW": "low_price",
        "ClsPric": "close_price",
        "CLOSE": "close_price",
        "SttlmPric": "settle_price",
        "SETTLE_PR": "settle_price",
        "PrvsClsgPric": "prev_close_price",
        "UndrlygPric": "underlying_price",
        "OpnIntrst": "oi",
        "OPEN_INT": "oi",
        "ChngInOpnIntrst": "chg_in_oi",
        "CHG_IN_OI": "chg_in_oi",
        "TtlTradgVol": "volume",
        "CONTRACTS": "volume",
        "TtlTrfVal": "turnover",
        "VAL_INLAKH": "turnover",
        "NewBrdLotQty": "lot_size",
    }

    def __init__(self, symbol: str = "NIFTY", default_lot_size: int = 75):
        self.symbol = symbol.upper()
        self.default_lot_size = default_lot_size

    @staticmethod
    def _parse_nse_date_series(values: pd.Series) -> pd.Series:
        """Parse ISO dates as YYYY-MM-DD; use day-first only for legacy NSE formats."""
        text = values.astype("string").str.strip()
        iso_mask = text.str.fullmatch(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", na=False)
        parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")

        if iso_mask.any():
            parsed.loc[iso_mask] = pd.to_datetime(
                text.loc[iso_mask], format="%Y-%m-%d", errors="coerce"
            )
        legacy_mask = ~iso_mask & text.notna() & text.ne("")
        if legacy_mask.any():
            parsed.loc[legacy_mask] = pd.to_datetime(
                text.loc[legacy_mask], format="mixed", dayfirst=True, errors="coerce"
            )

        invalid = parsed.isna()
        if invalid.any():
            examples = text.loc[invalid].dropna().unique().tolist()[:5]
            raise ValueError(f"Invalid NSE Bhavcopy date value(s): {examples}")
        return parsed

    def read_bhavcopy_file(self, filepath: str) -> pd.DataFrame:
        if filepath.lower().endswith(".zip"):
            with zipfile.ZipFile(filepath, "r") as zf:
                csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if not csv_names:
                    raise ValueError(f"No CSV found inside {filepath}")
                with zf.open(csv_names[0]) as f:
                    raw = pd.read_csv(f)
        else:
            raw = pd.read_csv(filepath)

        raw.columns = [c.strip() for c in raw.columns]
        rename_dict = {c: self.BHAV_COL_MAP[c] for c in raw.columns if c in self.BHAV_COL_MAP}
        df = raw.rename(columns=rename_dict).copy()

        df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
        df = df[df["symbol"] == self.symbol].copy()

        df["instrument_type"] = df["instrument_type"].astype(str).str.strip().str.upper().replace({
            "OPTIDX": "IDO",
            "FUTIDX": "IDF",
        })
        df = df[df["instrument_type"].isin(["IDO", "IDF"])].copy()

        # ISO UDiFF dates must not be interpreted with dayfirst=True.
        df["trade_date_dt"] = self._parse_nse_date_series(df["trade_date"])
        df["expiry_date_dt"] = self._parse_nse_date_series(df["expiry_date"])
        df["trade_date"] = df["trade_date_dt"].dt.strftime("%Y-%m-%d")
        df["expiry_date"] = df["expiry_date_dt"].dt.strftime("%Y-%m-%d")

        num_cols = [
            "strike", "open_price", "high_price", "low_price", "close_price",
            "settle_price", "prev_close_price", "underlying_price",
            "oi", "chg_in_oi", "volume", "turnover", "lot_size"
        ]
        for col in num_cols:
            if col not in df.columns:
                df[col] = np.nan
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df["lot_size"] = df["lot_size"].fillna(self.default_lot_size).astype(int)
        df.loc[df["lot_size"] <= 0, "lot_size"] = self.default_lot_size

        futs = df[df["instrument_type"] == "IDF"].sort_values("expiry_date_dt")
        if not futs.empty:
            near_fut_close = float(futs.iloc[0]["close_price"])
            spot_val = futs.iloc[0]["underlying_price"]
            spot_close = float(spot_val) if pd.notna(spot_val) and spot_val > 0 else near_fut_close
        else:
            valid_spot = df["underlying_price"].dropna()
            spot_close = float(valid_spot.iloc[0]) if not valid_spot.empty else 0.0
            near_fut_close = spot_close

        opts = df[df["instrument_type"] == "IDO"].copy()
        opts["option_type"] = opts["option_type"].astype(str).str.strip().str.upper()
        opts = opts[opts["option_type"].isin(["CE", "PE"])].copy()

        opts["spot_close"] = spot_close
        opts["futures_close"] = near_fut_close
        opts["prev_close_price"] = opts["prev_close_price"].fillna(opts["close_price"])
        opts["settle_price"] = opts["settle_price"].fillna(opts["close_price"])
        opts["oi"] = opts["oi"].fillna(0).astype(int)
        opts["chg_in_oi"] = opts["chg_in_oi"].fillna(0).astype(int)
        opts["volume"] = opts["volume"].fillna(0).astype(int)

        ohlc_proxy = (opts["open_price"] + opts["high_price"] + opts["low_price"] + 2.0 * opts["close_price"]) / 5.0
        calc_vwap = np.where(
            (opts["volume"] > 0) & (opts["turnover"] > 0),
            opts["turnover"] / opts["volume"],
            ohlc_proxy,
        )
        in_range = (calc_vwap >= opts["low_price"] * 0.95) & (calc_vwap <= opts["high_price"] * 1.05)
        opts["vwap"] = np.where(in_range, calc_vwap, ohlc_proxy)

        opts["oi_contracts"] = opts["oi"] / opts["lot_size"]
        opts["chg_oi_contracts"] = opts["chg_in_oi"] / opts["lot_size"]
        opts["vol_contracts"] = opts["volume"] / opts["lot_size"]

        return opts

    def load_bhavcopy_directory(self, data_dir: str, max_sessions: int = 35) -> pd.DataFrame:
        patterns = [
            os.path.join(data_dir, "*BhavCopy*.csv"),
            os.path.join(data_dir, "*BhavCopy*.zip"),
            os.path.join(data_dir, "*bhav*.csv"),
            os.path.join(data_dir, "*bhav*.zip"),
        ]
        files = []
        for p in patterns:
            files.extend(glob.glob(p))
        files = sorted(set(files))
        if not files:
            raise FileNotFoundError(f"No NSE Bhavcopy files found in {data_dir}")

        frames = [self.read_bhavcopy_file(fp) for fp in files]
        combined = pd.concat(frames, ignore_index=True)
        unique_dates = sorted(combined["trade_date"].unique())[-max_sessions:]
        combined = combined[combined["trade_date"].isin(unique_dates)].copy()
        combined.sort_values(["trade_date", "expiry_date", "strike", "option_type"], inplace=True)
        return combined.reset_index(drop=True)

    def load_participant_oi_directory(self, data_dir: str) -> pd.DataFrame:
        files = sorted(glob.glob(os.path.join(data_dir, "*participant_oi*.csv")))
        if not files:
            return pd.DataFrame()

        records = []
        for fp in files:
            fname = os.path.basename(fp)
            digits = "".join(ch for ch in fname if ch.isdigit())
            date_str = fname
            if len(digits) == 8:
                date_str = f"{digits[4:8]}-{digits[2:4]}-{digits[0:2]}"

            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            header_idx = 0
            for idx, line in enumerate(lines):
                if "Client Type" in line:
                    header_idx = idx
                    break
            df = pd.read_csv(fp, skiprows=header_idx)
            df.columns = [c.strip() for c in df.columns]
            if "Client Type" not in df.columns:
                continue
            df["Client Type"] = df["Client Type"].astype(str).str.strip()
            df = df[df["Client Type"].isin(["Client", "DII", "FII", "Pro"])].copy()
            df["trade_date"] = date_str
            records.append(df)

        return pd.concat(records, ignore_index=True) if records else pd.DataFrame()

    def load_fovolt_directory(self, data_dir: str) -> Dict[str, float]:
        files = sorted(glob.glob(os.path.join(data_dir, "*FOVOLT*.csv")))
        vol_map: Dict[str, float] = {}
        for fp in files:
            try:
                df = pd.read_csv(fp)
                df.columns = [c.strip() for c in df.columns]
                sym_col = [c for c in df.columns if "Symbol" in c][0]
                sub = df[df[sym_col].astype(str).str.strip().str.upper() == self.symbol]
                if sub.empty:
                    continue
                date_col = [c for c in df.columns if "Date" in c][0]
                ann_cols = [c for c in df.columns if "Annualised" in c or "Underlying" in c]
                val_col = ann_cols[-1]
                dt_str = pd.to_datetime(sub.iloc[0][date_col], format="mixed", dayfirst=True).strftime("%Y-%m-%d")
                vol_val = float(sub.iloc[0][val_col])
                vol_map[dt_str] = vol_val * 100.0 if vol_val < 1.5 else vol_val
            except Exception:
                continue
        return vol_map

"""
Data models strictly separating Observed NSE EOD Market Telemetry
from Estimated Seller Positioning and Calculated Risk Triggers.
"""
from dataclasses import dataclass, asdict
from typing import List, Dict, Any


@dataclass
class ObservedStrikeEOD:
    """Direct ground-truth telemetry parsed from NSE EOD Bhavcopy."""
    trade_date: str
    expiry_date: str
    dte: int
    strike: float
    option_type: str  # "CE" or "PE"
    spot_close: float
    futures_close: float
    lot_size: int
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    settle_price: float
    prev_close_price: float
    price_change: float
    price_change_pct: float
    oi: int
    chg_in_oi: int
    volume: int
    turnover: float
    vwap: float
    oi_contracts: float
    chg_oi_contracts: float
    vol_contracts: float
    iv: float
    delta: float
    gamma: float
    theta: float
    vega: float


@dataclass
class EstimatedSellerPosition:
    """Inferred positioning metrics (never presented as exact exchange fills)."""
    est_entry_low: float
    est_entry_mid: float
    est_entry_high: float
    entry_dispersion: float
    estimation_confidence_pct: float
    intensity_5d: float
    intensity_22d: float
    composite_sdi_zscore: float
    writing_concentration: str
    concentration_percentile: float
    accumulation_status: str
    eod_capitulation_flag: bool
    institutional_alignment: str


@dataclass
class CalculatedTriggerZones:
    """Model-derived breakeven, danger premium, and BSM-inverted spot danger levels."""
    seller_breakeven_premium: float
    seller_breakeven_spot: float
    danger_premium: float
    danger_spot_low: float
    danger_spot_high: float
    danger_spot_primary: float
    confirmation_rule: str
    next_day_role: str


@dataclass
class StrikeIntelligenceRecord:
    """Complete per-strike intelligence report combining Observed, Estimated, and Calculated layers."""
    strike: float
    option_type: str
    observed: ObservedStrikeEOD
    estimated: EstimatedSellerPosition
    calculated: CalculatedTriggerZones

    def to_flat_dict(self) -> Dict[str, Any]:
        return {
            "strike": self.strike,
            "option_type": self.option_type,
            "dte": self.observed.dte,
            "eod_premium_observed": round(self.observed.close_price, 2),
            "prev_premium_observed": round(self.observed.prev_close_price, 2),
            "premium_movement": round(self.observed.price_change, 2),
            "premium_movement_pct": round(self.observed.price_change_pct, 2),
            "oi_observed": self.observed.oi,
            "chg_in_oi_observed": self.observed.chg_in_oi,
            "volume_observed": self.observed.volume,
            "iv_pct": round(self.observed.iv * 100.0, 2),
            "delta": round(self.observed.delta, 4),
            "gamma": round(self.observed.gamma, 6),
            "theta": round(self.observed.theta, 2),
            "vega": round(self.observed.vega, 2),
            "writing_concentration": self.estimated.writing_concentration,
            "concentration_percentile": round(self.estimated.concentration_percentile, 1),
            "est_entry_zone_low": round(self.estimated.est_entry_low, 2),
            "est_entry_zone_mid": round(self.estimated.est_entry_mid, 2),
            "est_entry_zone_high": round(self.estimated.est_entry_high, 2),
            "estimation_confidence_pct": round(self.estimated.estimation_confidence_pct, 1),
            "intensity_5d": round(self.estimated.intensity_5d, 2),
            "intensity_22d": round(self.estimated.intensity_22d, 2),
            "composite_sdi_zscore": round(self.estimated.composite_sdi_zscore, 2),
            "seller_status_inferred": self.estimated.accumulation_status,
            "eod_capitulation_flag": self.estimated.eod_capitulation_flag,
            "danger_premium_calc": round(self.calculated.danger_premium, 2),
            "danger_spot_primary_calc": round(self.calculated.danger_spot_primary, 2),
            "danger_spot_band": f"{round(self.calculated.danger_spot_low, 1)} - {round(self.calculated.danger_spot_high, 1)}",
            "next_day_role": self.calculated.next_day_role,
            "confirmation_rule": self.calculated.confirmation_rule,
        }


@dataclass
class OpeningGapContingency:
    """Conditional execution playbook for 9:15 AM open without pre-market feed."""
    scenario: str
    open_spot_condition: str
    seller_impact: str
    execution_rule: str


@dataclass
class SidewaysRegimeAssessment:
    """5-rule detector for avoiding choppy / theta-trap markets."""
    is_no_trade: bool
    verdict: str
    triggered_rules_count: int
    total_rules: int
    corridor_points: float
    atr_14_points: float
    corridor_to_atr_ratio: float
    sideways_box_low: float
    sideways_box_high: float
    reasons: List[str]


@dataclass
class NextDayIntelligenceReport:
    """Complete EOD-generated intelligence brief for the next trading session."""
    as_of_date: str
    next_trading_hint: str
    expiry_date: str
    dte: int
    spot_close: float
    futures_close: float
    atr_14: float
    nse_eod_volatility_pct: float
    atm_iv_pct: float
    participant_summary: Dict[str, Any]
    regime: SidewaysRegimeAssessment
    primary_resistance: Dict[str, Any]
    major_resistance: Dict[str, Any]
    primary_support: Dict[str, Any]
    major_support: Dict[str, Any]
    strongest_resistance: Dict[str, Any]
    strongest_support: Dict[str, Any]
    actionability: Dict[str, Any]
    ce_danger_zones: List[Dict[str, Any]]
    pe_danger_zones: List[Dict[str, Any]]
    vacated_capitulation_strikes: List[Dict[str, Any]]
    gap_contingencies: List[OpeningGapContingency]
    strike_table: List[Dict[str, Any]]
    ml_outcome_probabilities: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

"""
Black-Scholes-Merton Forward Option Pricing, Implied Volatility Solver,
Exact Option Greeks, and Spot Danger Level Inversion Engine.
"""
import math
from typing import Dict
import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq


def bsm_price(
    F: float,
    K: float,
    T: float,
    sigma: float,
    option_type: str,
    r: float = 0.065,
) -> float:
    if T <= 1e-6 or sigma <= 1e-6:
        return max(0.0, F - K) if option_type == "CE" else max(0.0, K - F)

    df = math.exp(-r * T)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    if option_type == "CE":
        return df * (F * norm.cdf(d1) - K * norm.cdf(d2))
    return df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


def bsm_greeks(
    F: float,
    K: float,
    T: float,
    sigma: float,
    option_type: str,
    r: float = 0.065,
) -> Dict[str, float]:
    T_eff = max(T, 1.0 / (252.0 * 75.0))
    sig_eff = max(sigma, 0.01)
    df = math.exp(-r * T_eff)
    sqrt_T = math.sqrt(T_eff)

    d1 = (math.log(F / K) + 0.5 * sig_eff * sig_eff * T_eff) / (sig_eff * sqrt_T)
    d2 = d1 - sig_eff * sqrt_T
    pdf_d1 = norm.pdf(d1)

    if option_type == "CE":
        delta = df * norm.cdf(d1)
        theta_annual = (
            -df * F * pdf_d1 * sig_eff / (2.0 * sqrt_T)
            - r * df * K * norm.cdf(d2)
            + r * df * F * norm.cdf(d1)
        )
    else:
        delta = -df * norm.cdf(-d1)
        theta_annual = (
            -df * F * pdf_d1 * sig_eff / (2.0 * sqrt_T)
            + r * df * K * norm.cdf(-d2)
            - r * df * F * norm.cdf(-d1)
        )

    gamma = df * pdf_d1 / (F * sig_eff * sqrt_T)
    theta_daily = theta_annual / 252.0
    vega_1pct = (df * F * pdf_d1 * sqrt_T) / 100.0

    return {
        "delta": float(delta),
        "gamma": float(gamma),
        "theta": float(theta_daily),
        "vega": float(vega_1pct),
    }


def implied_volatility(
    market_price: float,
    F: float,
    K: float,
    T: float,
    option_type: str,
    r: float = 0.065,
) -> float:
    if T <= 1e-6 or market_price <= 0.05:
        return 0.12

    df = math.exp(-r * T)
    intrinsic = df * max(0.0, F - K) if option_type == "CE" else df * max(0.0, K - F)
    if market_price <= intrinsic + 0.05:
        return 0.05

    def objective(sig: float) -> float:
        return bsm_price(F, K, T, sig, option_type, r) - market_price

    try:
        iv = brentq(objective, 0.01, 3.0, xtol=1e-5, maxiter=60)
        return float(np.clip(iv, 0.03, 2.50))
    except ValueError:
        return 0.14


def solve_spot_danger_level(
    danger_premium: float,
    K: float,
    T_next: float,
    iv_stress: float,
    option_type: str,
    basis_spread: float = 0.0,
    r: float = 0.065,
) -> float:
    T_eff = max(T_next, 0.25 / 252.0)

    def obj(spot: float) -> float:
        F_est = spot + basis_spread
        return bsm_price(F_est, K, T_eff, iv_stress, option_type, r) - danger_premium

    low_s, high_s = (K * 0.70, K * 1.35) if option_type == "CE" else (K * 0.65, K * 1.30)

    try:
        if obj(low_s) * obj(high_s) <= 0:
            return float(brentq(obj, low_s, high_s, xtol=0.05, maxiter=60))
    except Exception:
        pass

    if option_type == "CE":
        return float(K + danger_premium * 0.65 - basis_spread)
    return float(K - danger_premium * 0.65 - basis_spread)

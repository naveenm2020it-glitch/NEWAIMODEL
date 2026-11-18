const BSMEngine = (() => {
  function normPdf(x) {
    return Math.exp(-0.5 * x * x) / Math.sqrt(2.0 * Math.PI);
  }

  function normCdf(x) {
    const sign = x < 0 ? -1 : 1;
    const absX = Math.abs(x) / Math.sqrt(2.0);
    const t = 1.0 / (1.0 + 0.3275911 * absX);
    const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741;
    const a4 = -1.453152027, a5 = 1.061405429;
    const erf = 1.0 - (((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t) * Math.exp(-absX * absX);
    return 0.5 * (1.0 + sign * erf);
  }

  function bsmPrice(F, K, T, sigma, optionType, r = 0.065) {
    if (T <= 1e-6 || sigma <= 1e-6) {
      return optionType === "CE" ? Math.max(0.0, F - K) : Math.max(0.0, K - F);
    }
    const df = Math.exp(-r * T);
    const sqrtT = Math.sqrt(T);
    const d1 = (Math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT);
    const d2 = d1 - sigma * sqrtT;
    if (optionType === "CE") return df * (F * normCdf(d1) - K * normCdf(d2));
    return df * (K * normCdf(-d2) - F * normCdf(-d1));
  }

  function bsmGreeks(F, K, T, sigma, optionType, r = 0.065) {
    const Teff = Math.max(T, 1.0 / (252.0 * 75.0));
    const sig = Math.max(sigma, 0.01);
    const df = Math.exp(-r * Teff);
    const sqrtT = Math.sqrt(Teff);
    const d1 = (Math.log(F / K) + 0.5 * sig * sig * Teff) / (sig * sqrtT);
    const d2 = d1 - sig * sqrtT;
    const pdf = normPdf(d1);

    let delta, thetaAnnual;
    if (optionType === "CE") {
      delta = df * normCdf(d1);
      thetaAnnual = -df * F * pdf * sig / (2.0 * sqrtT) - r * df * K * normCdf(d2) + r * df * F * normCdf(d1);
    } else {
      delta = -df * normCdf(-d1);
      thetaAnnual = -df * F * pdf * sig / (2.0 * sqrtT) + r * df * K * normCdf(-d2) - r * df * F * normCdf(-d1);
    }
    return {
      delta,
      gamma: df * pdf / (F * sig * sqrtT),
      theta: thetaAnnual / 252.0,
      vega: (df * F * pdf * sqrtT) / 100.0
    };
  }

  function brentRoot(fn, a, b, tol = 1e-5, maxIter = 60) {
    let fa = fn(a), fb = fn(b);
    if (fa * fb > 0) return null;
    if (Math.abs(fa) < Math.abs(fb)) { [a, b] = [b, a]; [fa, fb] = [fb, fa]; }
    let c = a, fc = fa, d = b - a, e = d;
    for (let iter = 0; iter < maxIter; iter++) {
      if (Math.abs(fc) < Math.abs(fb)) { a = b; b = c; c = a; fa = fb; fb = fc; fc = fa; }
      const tol1 = 2.0 * 2.22e-16 * Math.abs(b) + 0.5 * tol;
      const xm = 0.5 * (c - b);
      if (Math.abs(xm) <= tol1 || fb === 0.0) return b;
      if (Math.abs(e) >= tol1 && Math.abs(fa) > Math.abs(fb)) {
        const s = fb / fa;
        let p, q;
        if (a === c) { p = 2.0 * xm * s; q = 1.0 - s; }
        else {
          q = fa / fc;
          const r = fb / fc;
          p = s * (2.0 * xm * q * (q - r) - (b - a) * (r - 1.0));
          q = (q - 1.0) * (r - 1.0) * (s - 1.0);
        }
        if (p > 0) q = -q;
        p = Math.abs(p);
        if (2.0 * p < Math.min(3.0 * xm * q - Math.abs(tol1 * q), Math.abs(e * q))) { e = d; d = p / q; }
        else { d = xm; e = d; }
      } else { d = xm; e = d; }
      a = b; fa = fb;
      b += Math.abs(d) > tol1 ? d : (xm >= 0 ? tol1 : -tol1);
      fb = fn(b);
      if ((fb > 0 && fc > 0) || (fb < 0 && fc < 0)) { c = a; fc = fa; d = e = b - a; }
    }
    return b;
  }

  function impliedVolatility(marketPrice, F, K, T, optionType, r = 0.065) {
    if (T <= 1e-6 || marketPrice <= 0.05) return 0.12;
    const df = Math.exp(-r * T);
    const intrinsic = optionType === "CE" ? df * Math.max(0.0, F - K) : df * Math.max(0.0, K - F);
    if (marketPrice <= intrinsic + 0.05) return 0.05;
    const iv = brentRoot(sig => bsmPrice(F, K, T, sig, optionType, r) - marketPrice, 0.01, 3.0, 1e-5, 60);
    if (iv === null || Number.isNaN(iv)) return 0.14;
    return Math.min(2.5, Math.max(0.03, iv));
  }

  function solveSpotDangerLevel(dangerPremium, K, Tnext, ivStress, optionType, basisSpread = 0.0, r = 0.065) {
    const Teff = Math.max(Tnext, 0.25 / 252.0);
    const lowS = optionType === "CE" ? K * 0.70 : K * 0.65;
    const highS = optionType === "CE" ? K * 1.35 : K * 1.30;
    const root = brentRoot(
      spot => bsmPrice(spot + basisSpread, K, Teff, ivStress, optionType, r) - dangerPremium,
      lowS, highS, 0.05, 60
    );
    if (root !== null && !Number.isNaN(root)) return root;
    return optionType === "CE" ? K + dangerPremium * 0.65 - basisSpread : K - dangerPremium * 0.65 - basisSpread;
  }

  return { bsmPrice, bsmGreeks, impliedVolatility, solveSpotDangerLevel };
})();

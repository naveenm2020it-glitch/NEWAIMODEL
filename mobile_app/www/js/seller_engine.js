const SellerEngine = (() => {
  function computeSpotATR14(allRows) {
    const byDate = {};
    allRows.forEach(r => {
      const spot = Number(r && r.spot_close);
      if (r && r.trade_date && Number.isFinite(spot) && spot > 0 && !byDate[r.trade_date]) {
        byDate[r.trade_date] = spot;
      }
    });
    const dates = Object.keys(byDate).sort();
    const spots = dates.map(d => byDate[d]);
    if (spots.length < 2) return spots.length === 1 ? spots[0] * 0.0085 : 200.0;
    const diffs = [];
    for (let i = 1; i < spots.length; i++) diffs.push(Math.abs(spots[i] - spots[i - 1]));
    const slice = diffs.slice(-14);
    const rawAtr = (slice.reduce((a, b) => a + b, 0) / slice.length) / 0.72;
    const lastSpot = spots[spots.length - 1];
    return Math.min(lastSpot * 0.025, Math.max(lastSpot * 0.0045, rawAtr));
  }

  function selectActiveExpiry(latestRows, preferredExpiry = null) {
    if (!Array.isArray(latestRows) || latestRows.length === 0) {
      throw new Error("No latest-session NIFTY records are available.");
    }
    const oiByExp = {};
    latestRows.forEach(r => { oiByExp[r.expiry_date] = (oiByExp[r.expiry_date] || 0) + r.oi; });
    const asOfMs = new Date(latestRows[0].trade_date).getTime();
    const valid = Object.entries(oiByExp)
      .map(([exp, totalOi]) => ({ exp, dte: Math.round((new Date(exp).getTime() - asOfMs) / 86400000), totalOi }))
      .filter(x => x.dte >= 1);
    if (valid.length === 0) {
      throw new Error("No unexpired NIFTY option expiry was found in the latest EOD data.");
    }
    if (preferredExpiry) {
      const selected = valid.find(x => x.exp === preferredExpiry);
      if (!selected) throw new Error("The selected expiry is not a valid future expiry for this trading date.");
      return selected.exp;
    }
    const maxOi = Math.max(...valid.map(x => x.totalOi));
    const liquid = valid.filter(x => x.totalOi >= 0.35 * maxOi).sort((a, b) => a.dte - b.dte);
    if (liquid.length === 0) {
      throw new Error("No sufficiently liquid future NIFTY expiry was found.");
    }
    return liquid[0].exp;
  }

  function getAvailableExpiries(allRows, date) {
    if (!Array.isArray(allRows) || !date) return [];
    const rows = allRows.filter(r => r && r.trade_date === date && r.expiry_date && Number.isFinite(Number(r.oi)));
    const oiByExp = {};
    rows.forEach(r => { oiByExp[r.expiry_date] = (oiByExp[r.expiry_date] || 0) + Number(r.oi || 0); });
    const asOfMs = new Date(date + "T00:00:00").getTime();
    return Object.keys(oiByExp).filter(exp => /^\\d{4}-\\d{2}-\\d{2}$/.test(exp) &&
      Math.round((new Date(exp + "T00:00:00").getTime() - asOfMs) / 86400000) >= 1).sort();
  }

  function getDefaultExpiry(allRows, date) {
    const rows = (allRows || []).filter(r => r && r.trade_date === date);
    return selectActiveExpiry(rows);
  }

  function analyze(allRows, participantSummary = null, options = {}) {
    if (!Array.isArray(allRows) || allRows.length === 0) throw new Error("No valid EOD records available.");
    const requestedDate = options && options.date ? String(options.date) : null;
    const requestedExpiry = options && options.expiry ? String(options.expiry) : null;
    const validRows = allRows.filter(r =>
      r && /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(String(r.trade_date || "")) &&
      /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(String(r.expiry_date || "")) &&
      Number.isFinite(Number(r.strike)) && Number(r.strike) > 0 &&
      (r.option_type === "CE" || r.option_type === "PE") &&
      Number.isFinite(Number(r.close_price)) && Number(r.close_price) >= 0 &&
      Number.isFinite(Number(r.oi)) && Number(r.oi) >= 0 &&
      (!requestedDate || r.trade_date <= requestedDate)
    );
    if (validRows.length === 0) throw new Error("The imported data contains no usable NIFTY option records.");
    const allDates = [...new Set(validRows.map(r => r.trade_date))].sort();
    if (allDates.length === 0) throw new Error("No valid EOD dates available.");

    const latestDate = requestedDate || allDates[allDates.length - 1];
    if (!allDates.includes(latestDate)) throw new Error("No NSE option records are stored for the selected trading date.");
    const win22 = allDates.slice(-22);
    const lagMap = {};
    [...win22].reverse().forEach((d, idx) => { lagMap[d] = idx; });

    const latestAll = validRows.filter(r => r.trade_date === latestDate);
    if (latestAll.length === 0) throw new Error("No option records exist for the latest EOD date.");
    const targetExpiry = selectActiveExpiry(latestAll, requestedExpiry);

    const calDays = Math.max(1, Math.round((new Date(targetExpiry) - new Date(latestDate)) / 86400000));
    const dte = Math.max(1, Math.round(calDays * 5.0 / 7.0));
    const Tnow = dte / 252.0;
    const Tnext = Math.max(0.35, dte - 1.0) / 252.0;

    const latestExp = latestAll.filter(r => r.expiry_date === targetExpiry);
    if (latestExp.length === 0) throw new Error("The selected expiry has no option records.");
    const spotClose = Number(latestExp[0].spot_close);
    if (!Number.isFinite(spotClose) || spotClose <= 0) throw new Error("NIFTY spot close is missing or invalid in the latest EOD data.");
    const rawFuturesClose = Number(latestExp[0].futures_close);
    const futuresClose = Number.isFinite(rawFuturesClose) && rawFuturesClose > 0 ? rawFuturesClose : spotClose;
    const basisSpread = futuresClose - spotClose;
    const atr14 = computeSpotATR14(validRows);

    const minStrike = spotClose * 0.955;
    const maxStrike = spotClose * 1.045;
    const activeLatest = latestExp.filter(r => r.strike >= minStrike && r.strike <= maxStrike);
    if (activeLatest.length === 0) throw new Error("No strikes are available inside the analysis range for the selected expiry.");
    const hist22 = validRows.filter(r => win22.includes(r.trade_date) && r.strike >= minStrike && r.strike <= maxStrike);

    const prelim = activeLatest.map(row => {
      const K = row.strike;
      const optType = row.option_type;
      const closeP = row.close_price;
      const prevP = row.prev_close_price;
      const priceChg = closeP - prevP;
      const priceChgPct = prevP > 0.05 ? (priceChg / prevP) * 100.0 : 0.0;

      const iv = BSMEngine.impliedVolatility(closeP, futuresClose, K, Tnow, optType);
      const greeks = BSMEngine.bsmGreeks(futuresClose, K, Tnow, iv, optType);

      const subMap = {};
      hist22
        .filter(h => h.strike === K && h.option_type === optType)
        .forEach(h => {
          const j = lagMap[h.trade_date];
          const existing = subMap[j];
          const scoreNew = (h.expiry_date === targetExpiry ? 1e12 : 0) + h.oi;
          const scoreOld = existing ? ((existing.expiry_date === targetExpiry ? 1e12 : 0) + existing.oi) : -1;
          if (scoreNew > scoreOld) subMap[j] = h;
        });

      let i5 = 0.0, i22 = 0.0;
      const wPrices = [], wWeights = [];

      Object.entries(subMap).forEach(([jStr, h]) => {
        const j = parseInt(jStr, 10);
        const chgOiC = h.chg_oi_contracts;
        const volC = Math.max(h.vol_contracts, 1.0);
        const pChg = h.close_price - h.prev_close_price;

        if (chgOiC > 0) {
          const shortMult = pChg <= 0 ? 1.25 : 0.70;
          const stickiness = 1.0 + Math.min(chgOiC / volC, 1.0);
          const wScore = chgOiC * shortMult * stickiness;

          if (j < 5) i5 += Math.exp(-0.277 * j) * wScore;
          i22 += Math.exp(-0.063 * j) * wScore;

          const expW = h.expiry_date === targetExpiry ? 1.5 : 0.5;
          wPrices.push(h.vwap);
          wWeights.push(Math.exp(-0.15 * j) * expW * chgOiC);
        }
      });

      const standingBoost = row.oi_contracts * 0.22;
      const i5Total = i5 + standingBoost;
      const i22Total = i22 + standingBoost * 1.4;

      let pLow, pMid, pHigh, pStd, confPct;
      if (wPrices.length > 0) {
        const wSum = wWeights.reduce((a, b) => a + b, 0);
        pMid = wPrices.reduce((acc, p, idx) => acc + p * wWeights[idx], 0) / wSum;
        const pVar = wPrices.reduce((acc, p, idx) => acc + wWeights[idx] * Math.pow(p - pMid, 2), 0) / wSum;
        pStd = Math.sqrt(Math.max(0, pVar));
        const halfBand = Math.max(0.75 * pStd, pMid * 0.035);
        pLow = Math.max(1.0, pMid - halfBand);
        pHigh = pMid + halfBand;
        const relDisp = pStd / Math.max(pMid, 1.0);
        confPct = Math.min(94.0, Math.max(42.0, 88.0 - relDisp * 120.0 + Math.min(wPrices.length * 2.5, 10.0)));
      } else {
        pMid = Math.max(row.vwap, closeP);
        pStd = pMid * 0.05;
        pLow = Math.max(1.0, pMid * 0.95);
        pHigh = pMid * 1.05;
        confPct = 45.0;
      }

      return {
        obs: { ...row, dte, price_change: priceChg, price_change_pct: priceChgPct, iv, ...greeks },
        i5: i5Total, i22: i22Total, pLow, pMid, pHigh, pStd, confPct
      };
    });

    const mean = arr => arr.reduce((a, b) => a + b, 0) / Math.max(arr.length, 1);
    const std = (arr, m) => Math.sqrt(arr.reduce((a, b) => a + Math.pow(b - m, 2), 0) / Math.max(arr.length, 1)) + 1e-6;

    const i5Arr = prelim.map(x => x.i5);
    const i22Arr = prelim.map(x => x.i22);
    const m5 = mean(i5Arr), s5 = std(i5Arr, m5);
    const m22 = mean(i22Arr), s22 = std(i22Arr, m22);

    const sdiArr = prelim.map(x => 0.65 * ((x.i5 - m5) / s5) + 0.35 * ((x.i22 - m22) / s22));
    const atmSorted = [...prelim].sort((a, b) => Math.abs(a.obs.strike - spotClose) - Math.abs(b.obs.strike - spotClose));
    const atmIv = atmSorted.length >= 2 ? (atmSorted[0].obs.iv + atmSorted[1].obs.iv) / 2.0 : 0.13;

    const dteFactor = Math.min(1.50, Math.max(1.26, 1.26 + 0.035 * Math.min(dte, 7)));
    const ivShock = Math.min(0.032, Math.max(0.015, 0.015 + 0.08 * atmIv));

    const records = prelim.map((item, idx) => {
      const obs = item.obs;
      const sdi = sdiArr[idx];
      const pctRank = (sdiArr.filter(v => v <= sdi).length / sdiArr.length) * 100.0;
      const concLabel = (pctRank >= 80.0 && sdi > 0.45) ? "High" : (pctRank >= 50.0 ? "Moderate" : "Low");

      const prevOiEst = Math.max(obs.oi - obs.chg_in_oi, 1);
      const oiChgPct = (obs.chg_in_oi / prevOiEst) * 100.0;
      const capFlag = (oiChgPct <= -5.0) && (obs.close_price > item.pHigh) && (obs.price_change > 0);

      let accStatus = "Holding / Neutral";
      if (capFlag) accStatus = "Capitulation / Short Covering";
      else if (oiChgPct >= 5.0 && obs.price_change <= 0) accStatus = "Fresh Aggressive Accumulation";
      else if (oiChgPct >= 2.0) accStatus = "Persistent Accumulation";
      else if (oiChgPct <= -3.0) accStatus = "Partial Unwinding";

      const bePrem = item.pMid;
      const beSpot = obs.option_type === "CE" ? (obs.strike + bePrem) : (obs.strike - bePrem);

      const mtmDanger = item.pHigh * dteFactor;
      const atrDanger = obs.close_price + Math.abs(obs.delta) * (0.75 * atr14) + 0.5 * obs.gamma * Math.pow(0.75 * atr14, 2);
      const dangerPrem = Math.max(mtmDanger, atrDanger, obs.close_price * 1.18);

      const sDangerPrimary = BSMEngine.solveSpotDangerLevel(
        dangerPrem, obs.strike, Tnext, obs.iv + ivShock, obs.option_type, basisSpread
      );

      let role = obs.option_type === "CE" ? "Secondary CE" : "Secondary PE";
      if (capFlag) role = "Vacated Breakout Vacuum";
      else if (concLabel !== "Low") role = obs.option_type === "CE" ? "Resistance / CE Trap" : "Support / PE Trap";

      const confRule = capFlag
        ? `Sellers covered EOD (OI ${oiChgPct.toFixed(1)}%). Former wall acts as breakout flip zone.`
        : obs.option_type === "CE"
          ? `15m Close: NIFTY Spot > ${sDangerPrimary.toFixed(1)} AND ${obs.strike} CE > ₹${dangerPrem.toFixed(1)}`
          : `15m Close: NIFTY Spot < ${sDangerPrimary.toFixed(1)} AND ${obs.strike} PE > ₹${dangerPrem.toFixed(1)}`;

      return {
        strike: obs.strike, option_type: obs.option_type, dte: obs.dte,
        eod_premium: +obs.close_price.toFixed(2), prev_premium: +obs.prev_close_price.toFixed(2),
        premium_chg: +obs.price_change.toFixed(2), oi: obs.oi, chg_in_oi: obs.chg_in_oi,
        volume: obs.volume, iv_pct: +(obs.iv * 100.0).toFixed(2),
        delta: +obs.delta.toFixed(3), gamma: +obs.gamma.toFixed(5),
        writing_concentration: concLabel, concentration_pct: +pctRank.toFixed(1),
        est_entry_low: +item.pLow.toFixed(2), est_entry_mid: +item.pMid.toFixed(2),
        est_entry_high: +item.pHigh.toFixed(2), confidence_pct: +item.confPct.toFixed(1),
        intensity_5d: +item.i5.toFixed(1), intensity_22d: +item.i22.toFixed(1),
        sdi_zscore: +sdi.toFixed(2), seller_status: accStatus, capitulation_flag: capFlag,
        breakeven_spot: +beSpot.toFixed(1), danger_premium: +dangerPrem.toFixed(2),
        danger_spot: +sDangerPrimary.toFixed(1), next_day_role: role, confirmation_rule: confRule
      };
    });

    const ceCands = records
      .filter(r => r.option_type === "CE" && r.strike >= spotClose * 0.995 && !r.capitulation_flag)
      .sort((a, b) => b.sdi_zscore - a.sdi_zscore);
    const peCands = records
      .filter(r => r.option_type === "PE" && r.strike <= spotClose * 1.005 && !r.capitulation_flag)
      .sort((a, b) => b.sdi_zscore - a.sdi_zscore);

    if (ceCands.length === 0) {
      throw new Error("No eligible CE resistance candidates were found around NIFTY spot for the selected expiry.");
    }
    if (peCands.length === 0) {
      throw new Error("No eligible PE support candidates were found around NIFTY spot for the selected expiry.");
    }

    const primaryCE = ceCands[0];
    const majorCE = ceCands.find(r => r.strike > primaryCE.strike) || ceCands[1] || primaryCE;
    primaryCE.next_day_role = "Primary Resistance / CE Trap";
    if (majorCE.strike !== primaryCE.strike) majorCE.next_day_role = "Major Resistance";

    const primaryPE = peCands[0];
    const majorPE = peCands.find(r => r.strike < primaryPE.strike) || peCands[1] || primaryPE;
    primaryPE.next_day_role = "Primary Support / PE Trap";
    if (majorPE.strike !== primaryPE.strike) majorPE.next_day_role = "Major Support";

    const corridorPts = Math.max(0, primaryCE.strike - primaryPE.strike);
    const corridorRatio = corridorPts / Math.max(atr14, 1.0);
    const reasons = [];

    if (corridorRatio < 1.25) {
      reasons.push(`Tight Seller Corridor: ${primaryPE.strike} PE to ${primaryCE.strike} CE is ${corridorPts} pts (${corridorRatio.toFixed(2)}x ATR14 < 1.25x).`);
    }
    if (primaryCE.chg_in_oi > 0 && primaryPE.chg_in_oi > 0) {
      reasons.push(`Bilateral Defense: Both ${primaryCE.strike} CE (+${primaryCE.chg_in_oi.toLocaleString()}) and ${primaryPE.strike} PE (+${primaryPE.chg_in_oi.toLocaleString()}) added fresh OI.`);
    }
    if (primaryCE.premium_chg < 0 && primaryPE.premium_chg < 0) {
      reasons.push(`Theta Decay Dominance: Both primary CE (${primaryCE.premium_chg}) and PE (${primaryPE.premium_chg}) lost premium EOD.`);
    }
    const vacated = records.filter(r => r.capitulation_flag);
    if (vacated.length === 0) {
      reasons.push("Zero EOD Capitulation: No active strike showed seller short-covering in latest session.");
    }
    const minRunway = Math.min(
      Math.max(0, primaryCE.danger_spot - spotClose),
      Math.max(0, spotClose - primaryPE.danger_spot)
    );
    if (minRunway > 0.65 * atr14 && corridorRatio < 1.45) {
      reasons.push(`Insufficient Runway: Spot needs >${minRunway.toFixed(0)} pts just to reach seller danger triggers.`);
    }

    const isNoTrade = reasons.length >= 3;
    const flatLow = (spotClose - 0.25 * atr14).toFixed(1);
    const flatHigh = (spotClose + 0.25 * atr14).toFixed(1);

    const gapPlaybook = [
      {
        title: "1. Flat / Inside-Range Open",
        condition: `9:15 AM Spot opens between ${flatLow} and ${flatHigh}`,
        action: `Enforce NO TRADE inside [${primaryPE.strike} – ${primaryCE.strike}] unless a 15m candle closes above ${primaryCE.danger_spot} with ${primaryCE.strike} CE > ₹${primaryCE.danger_premium} (or below ${primaryPE.danger_spot} with ${primaryPE.strike} PE > ₹${primaryPE.danger_premium}).`
      },
      {
        title: "2. Gap-Up Open (CE Seller Stress)",
        condition: `9:15 AM Spot opens above ${primaryCE.breakeven_spot}`,
        action: `Wait for 9:30 AM (1st 15m close): If ${primaryCE.strike} CE holds > ₹${primaryCE.danger_premium} & Spot > ${primaryCE.danger_spot}, CE sellers are trapped → Bullish Continuation to ${majorCE.strike}. If CE drops below ₹${primaryCE.est_entry_high}, sellers defended → Gap-Fill Fade.`
      },
      {
        title: "3. Gap-Down Open (PE Seller Stress)",
        condition: `9:15 AM Spot opens below ${primaryPE.breakeven_spot}`,
        action: `Wait for 9:30 AM (1st 15m close): If ${primaryPE.strike} PE holds > ₹${primaryPE.danger_premium} & Spot < ${primaryPE.danger_spot}, PE sellers are trapped → Bearish Breakdown to ${majorPE.strike}. If PE drops below ₹${primaryPE.est_entry_high}, sellers defended → Gap-Fill Reversal.`
      }
    ];

    records.sort((a, b) => a.strike - b.strike || a.option_type.localeCompare(b.option_type));

    return {
      as_of_date: latestDate, expiry_date: targetExpiry, dte, sessions_loaded: allDates.length,
      spot_close: +spotClose.toFixed(2), futures_close: +futuresClose.toFixed(2),
      atr_14: +atr14.toFixed(1), atm_iv_pct: +(atmIv * 100.0).toFixed(2),
      participant_summary: participantSummary,
      regime: {
        is_no_trade: isNoTrade,
        verdict: isNoTrade ? "WAIT / NO TRADE — RANGE-BOUND PINNING REGIME" : "ACTIONABLE — WATCH DUAL-PRICE TRIGGERS",
        triggered_count: reasons.length, corridor_pts: corridorPts, corridor_ratio: +corridorRatio.toFixed(2),
        box_low: primaryPE.strike, box_high: primaryCE.strike, reasons
      },
      primary_resistance: primaryCE, major_resistance: majorCE,
      primary_support: primaryPE, major_support: majorPE,
      vacated_strikes: vacated, gap_playbook: gapPlaybook, strike_table: records
    };
  }

  return { analyze, getAvailableExpiries, getDefaultExpiry };
})();

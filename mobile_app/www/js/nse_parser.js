const NSEParser = (() => {
  const COL_MAP = {
    TradDt: "trade_date", TIMESTAMP: "trade_date",
    FinInstrmTp: "instrument_type", INSTRUMENT: "instrument_type",
    TckrSymb: "symbol", SYMBOL: "symbol",
    XpryDt: "expiry_date", EXPIRY_DT: "expiry_date",
    StrkPric: "strike", STRIKE_PR: "strike",
    OptnTp: "option_type", OPTION_TYP: "option_type",
    OpnPric: "open_price", OPEN: "open_price",
    HghPric: "high_price", HIGH: "high_price",
    LwPric: "low_price", LOW: "low_price",
    ClsPric: "close_price", CLOSE: "close_price",
    SttlmPric: "settle_price", SETTLE_PR: "settle_price",
    PrvsClsgPric: "prev_close_price",
    UndrlygPric: "underlying_price",
    OpnIntrst: "oi", OPEN_INT: "oi",
    ChngInOpnIntrst: "chg_in_oi", CHG_IN_OI: "chg_in_oi",
    TtlTradgVol: "volume", CONTRACTS: "volume",
    TtlTrfVal: "turnover", VAL_INLAKH: "turnover",
    NewBrdLotQty: "lot_size"
  };

  function parseCSVLine(line) {
    const out = [];
    let cur = "", inQuotes = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') inQuotes = !inQuotes;
      else if (ch === "," && !inQuotes) { out.push(cur.trim()); cur = ""; }
      else cur += ch;
    }
    out.push(cur.trim());
    return out;
  }

  function normalizeDate(rawStr) {
    if (!rawStr) return "";
    const s = rawStr.trim();
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
    const months = {
      JAN: "01", FEB: "02", MAR: "03", APR: "04", MAY: "05", JUN: "06",
      JUL: "07", AUG: "08", SEP: "09", OCT: "10", NOV: "11", DEC: "12"
    };
    const m1 = s.match(/^(\d{1,2})[-/]([A-Za-z]{3})[-/](\d{4})$/);
    if (m1) return `${m1[3]}-${months[m1[2].toUpperCase()] || "01"}-${m1[1].padStart(2, "0")}`;
    const m2 = s.match(/^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$/);
    if (m2) return `${m2[3]}-${m2[2].padStart(2, "0")}-${m2[1].padStart(2, "0")}`;
    const dt = new Date(s);
    return !Number.isNaN(dt.getTime()) ? dt.toISOString().slice(0, 10) : s;
  }

  function parseBhavcopyCSV(csvText, targetSymbol = "NIFTY", defaultLot = 75) {
    const lines = csvText.split(/\r?\n/).filter(l => l.trim().length > 0);
    if (lines.length < 2) return [];
    const rawHeaders = parseCSVLine(lines[0].replace(/^\uFEFF/, ""));
    const idxMap = {};
    rawHeaders.forEach((h, i) => { if (COL_MAP[h]) idxMap[COL_MAP[h]] = i; });
    if (idxMap.symbol === undefined || idxMap.strike === undefined) return [];

    const futRows = [], optRows = [];
    for (let r = 1; r < lines.length; r++) {
      const cols = parseCSVLine(lines[r]);
      if ((cols[idxMap.symbol] || "").toUpperCase() !== targetSymbol) continue;
      let inst = (cols[idxMap.instrument_type] || "").toUpperCase();
      if (inst === "OPTIDX") inst = "IDO";
      if (inst === "FUTIDX") inst = "IDF";
      if (inst !== "IDO" && inst !== "IDF") continue;

      const tradeDate = normalizeDate(cols[idxMap.trade_date]);
      const expiryDate = normalizeDate(cols[idxMap.expiry_date]);
      const closePrice = parseFloat(cols[idxMap.close_price]) || 0;
      const underlyingPrice = parseFloat(cols[idxMap.underlying_price]) || 0;

      if (inst === "IDF") {
        futRows.push({ tradeDate, expiryDate, closePrice, underlyingPrice });
        continue;
      }

      const optType = (cols[idxMap.option_type] || "").toUpperCase();
      if (optType !== "CE" && optType !== "PE") continue;

      const openPrice = parseFloat(cols[idxMap.open_price]) || closePrice;
      const highPrice = parseFloat(cols[idxMap.high_price]) || closePrice;
      const lowPrice = parseFloat(cols[idxMap.low_price]) || closePrice;
      const settlePrice = parseFloat(cols[idxMap.settle_price]) || closePrice;
      const prevClosePrice = parseFloat(cols[idxMap.prev_close_price]) || closePrice;
      const strike = parseFloat(cols[idxMap.strike]) || 0;
      const oi = parseInt(cols[idxMap.oi], 10) || 0;
      const chgInOi = parseInt(cols[idxMap.chg_in_oi], 10) || 0;
      const volume = parseInt(cols[idxMap.volume], 10) || 0;
      const turnover = parseFloat(cols[idxMap.turnover]) || 0;
      const rawLot = parseInt(cols[idxMap.lot_size], 10) || defaultLot;
      const lotSize = rawLot > 0 ? rawLot : defaultLot;

      const ohlcProxy = (openPrice + highPrice + lowPrice + 2.0 * closePrice) / 5.0;
      const rawVwap = (volume > 0 && turnover > 0) ? (turnover / volume) : ohlcProxy;
      const vwap = (rawVwap >= lowPrice * 0.95 && rawVwap <= highPrice * 1.05) ? rawVwap : ohlcProxy;

      optRows.push({
        trade_date: tradeDate, expiry_date: expiryDate, strike, option_type: optType,
        open_price: openPrice, high_price: highPrice, low_price: lowPrice,
        close_price: closePrice, settle_price: settlePrice, prev_close_price: prevClosePrice,
        underlying_price: underlyingPrice, oi, chg_in_oi: chgInOi, volume, turnover, vwap,
        lot_size: lotSize, oi_contracts: oi / lotSize, chg_oi_contracts: chgInOi / lotSize, vol_contracts: volume / lotSize
      });
    }

    const futByDate = {};
    futRows.sort((a, b) => a.expiryDate.localeCompare(b.expiryDate));
    futRows.forEach(f => {
      if (!futByDate[f.tradeDate]) {
        futByDate[f.tradeDate] = {
          futures_close: f.closePrice,
          spot_close: f.underlyingPrice > 0 ? f.underlyingPrice : f.closePrice
        };
      }
    });

    optRows.forEach(row => {
      const ref = futByDate[row.trade_date];
      row.futures_close = ref ? ref.futures_close : (row.underlying_price || 0);
      row.spot_close = ref ? ref.spot_close : (row.underlying_price || row.futures_close);
    });
    return optRows;
  }

  function parseParticipantCSV(csvText, fileName = "") {
    const lines = csvText.split(/\r?\n/).filter(l => l.trim().length > 0);
    const headerIdx = lines.findIndex(l => l.includes("Client Type"));
    if (headerIdx < 0) return null;
    const headers = parseCSVLine(lines[headerIdx]);
    const clientIdx = headers.findIndex(h => h === "Client Type");
    const callLongIdx = headers.findIndex(h => h.includes("Option Index Call Long"));
    const callShortIdx = headers.findIndex(h => h.includes("Option Index Call Short"));
    const putLongIdx = headers.findIndex(h => h.includes("Option Index Put Long"));
    const putShortIdx = headers.findIndex(h => h.includes("Option Index Put Short"));
    if (clientIdx < 0 || callLongIdx < 0) return null;

    let instNetCall = 0, instNetPut = 0;
    for (let r = headerIdx + 1; r < lines.length; r++) {
      const cols = parseCSVLine(lines[r]);
      const cType = (cols[clientIdx] || "").trim();
      if (cType === "FII" || cType === "Pro") {
        instNetCall += (parseFloat(cols[callLongIdx]) || 0) - (parseFloat(cols[callShortIdx]) || 0);
        instNetPut += (parseFloat(cols[putLongIdx]) || 0) - (parseFloat(cols[putShortIdx]) || 0);
      }
    }
    const digits = fileName.replace(/\D/g, "");
    const dateHint = digits.length === 8 ? `${digits.slice(4, 8)}-${digits.slice(2, 4)}-${digits.slice(0, 2)}` : "Latest EOD";
    return {
      available: true, as_of: dateHint,
      inst_net_call_contracts: Math.round(instNetCall),
      inst_net_put_contracts: Math.round(instNetPut),
      pro_fii_call_short_dominant: instNetCall < 0,
      pro_fii_put_short_dominant: instNetPut < 0
    };
  }

  function generateDemo22Sessions() {
    const rows = [];
    const lotSize = 75;
    const expiryDate = "2026-11-26";
    const baseSpots = [
      24820, 24865, 24840, 24910, 24950, 24925, 24980, 25030, 25010, 24970,
      24940, 24990, 25045, 25080, 25055, 25015, 24985, 25020, 25040, 25010,
      24985, 24995
    ];
    const strikes = [24600, 24700, 24800, 24900, 25000, 25100, 25200, 25300, 25400];

    for (let d = 0; d < 22; d++) {
      const dayNum = String(d + 1).padStart(2, "0");
      const tradeDate = `2026-10-${dayNum}`;
      const spot = baseSpots[d];
      const fut = spot + 42;
      const dte = Math.max(3, 25 - d);
      const T = dte / 252.0;

      strikes.forEach(K => {
        ["CE", "PE"].forEach(optType => {
          const iv = 0.125 + Math.abs(K - spot) / 25000 * 0.18;
          const closeP = Math.max(4.5, BSMEngine.bsmPrice(fut, K, T, iv, optType));
          const prevP = closeP * (1.0 + (optType === "CE" ? 0.04 : 0.03));
          const isPrimaryWall = (optType === "CE" && K === 25100) || (optType === "PE" && K === 24900);
          const isMajorWall = (optType === "CE" && K === 25200) || (optType === "PE" && K === 24800);
          const baseOi = isPrimaryWall ? 78000 * lotSize : (isMajorWall ? 65000 * lotSize : 24000 * lotSize);
          const dailyAdd = isPrimaryWall ? (2600 + d * 150) * lotSize : (isMajorWall ? (1700 + d * 80) * lotSize : 350 * lotSize);
          const vol = dailyAdd * 4.5;

          rows.push({
            trade_date: tradeDate, expiry_date: expiryDate, strike: K, option_type: optType,
            open_price: +(prevP * 0.99).toFixed(2),
            high_price: +(Math.max(prevP, closeP) * 1.06).toFixed(2),
            low_price: +(closeP * 0.94).toFixed(2),
            close_price: +closeP.toFixed(2),
            settle_price: +closeP.toFixed(2),
            prev_close_price: +prevP.toFixed(2),
            spot_close: spot, futures_close: fut,
            oi: Math.round(baseOi + d * dailyAdd * 0.55),
            chg_in_oi: Math.round(dailyAdd),
            volume: Math.round(vol),
            turnover: +(vol * closeP * 1.03).toFixed(2),
            vwap: +(closeP * 1.04).toFixed(2),
            lot_size: lotSize,
            oi_contracts: (baseOi + d * dailyAdd * 0.55) / lotSize,
            chg_oi_contracts: dailyAdd / lotSize,
            vol_contracts: vol / lotSize
          });
        });
      });
    }
    return rows;
  }

  return { parseBhavcopyCSV, parseParticipantCSV, generateDemo22Sessions };
})();

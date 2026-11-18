const STORAGE_KEY_ROWS = "nifty_eod_rolling_rows_v1";
const STORAGE_KEY_PART = "nifty_eod_participant_v1";

function loadStoredRows() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_ROWS);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch (e) {
    return [];
  }
}

function saveStoredRows(rows) {
  const dates = [...new Set(rows.map(r => r.trade_date))].sort().slice(-25);
  const trimmed = rows.filter(r => dates.includes(r.trade_date));
  localStorage.setItem(STORAGE_KEY_ROWS, JSON.stringify(trimmed));
  return trimmed;
}

function mergeRows(existing, incoming) {
  const map = new Map();
  existing.forEach(r => map.set(`${r.trade_date}|${r.expiry_date}|${r.strike}|${r.option_type}`, r));
  incoming.forEach(r => map.set(`${r.trade_date}|${r.expiry_date}|${r.strike}|${r.option_type}`, r));
  return Array.from(map.values());
}

function ingestSyncPayload(payload) {
  if (!payload) return 0;
  let existing = loadStoredRows();
  let added = 0;

  if (Array.isArray(payload.bhavCsvList)) {
    for (const csvText of payload.bhavCsvList) {
      const parsed = NSEParser.parseBhavcopyCSV(csvText, "NIFTY", 75);
      if (parsed.length > 0) {
        existing = mergeRows(existing, parsed);
        added += parsed.length;
      }
    }
  }

  if (payload.participantCsv && payload.participantCsv.trim().length > 0) {
    const part = NSEParser.parseParticipantCSV(payload.participantCsv, payload.participantFileName || "");
    if (part) localStorage.setItem(STORAGE_KEY_PART, JSON.stringify(part));
  }

  if (added > 0) {
    saveStoredRows(existing);
  }
  return added;
}

function renderReport(report) {
  document.getElementById("headerMeta").textContent =
    `EOD: ${report.as_of_date} | Expiry: ${report.expiry_date} (${report.dte} DTE) | ${report.sessions_loaded} Sessions Stored`;

  document.getElementById("kpiSpot").textContent = report.spot_close.toLocaleString("en-IN");
  document.getElementById("kpiAtr").textContent = `${report.atr_14} pts`;
  document.getElementById("kpiIv").textContent = `${report.atm_iv_pct}%`;
  document.getElementById("kpiCorridor").textContent = `${report.regime.box_low} – ${report.regime.box_high}`;

  const banner = document.getElementById("regimeBanner");
  banner.className = `card regime-card ${report.regime.is_no_trade ? "regime-warn" : "regime-ok"}`;
  document.getElementById("regimeVerdict").textContent = report.regime.verdict;
  document.getElementById("regimeSub").textContent =
    `Sideways Trap Rules Triggered: ${report.regime.triggered_count}/5 | Corridor/ATR14: ${report.regime.corridor_ratio}x`;

  const reasonsUl = document.getElementById("regimeReasons");
  reasonsUl.innerHTML = report.regime.reasons.map(r => `<li>${r}</li>`).join("");

  const partEl = document.getElementById("participantBar");
  if (report.participant_summary && report.participant_summary.available) {
    const p = report.participant_summary;
    partEl.textContent = `Pro+FII Net Index Calls: ${p.inst_net_call_contracts.toLocaleString()} | Net Index Puts: ${p.inst_net_put_contracts.toLocaleString()} (${p.as_of})`;
    partEl.style.display = "block";
  } else {
    partEl.style.display = "none";
  }

  const walls = [
    { label: "Major Resistance", data: report.major_resistance, cls: "tag-res" },
    { label: "Primary Resistance (CE Trap)", data: report.primary_resistance, cls: "tag-res" },
    { label: "Primary Support (PE Trap)", data: report.primary_support, cls: "tag-sup" },
    { label: "Major Support", data: report.major_support, cls: "tag-sup" }
  ];
  document.getElementById("wallsGrid").innerHTML = walls.map(w => `
    <div class="wall-box">
      <div class="wall-top">
        <span class="badge ${w.cls}">${w.label}</span>
        <strong>${w.data.strike} ${w.data.option_type}</strong>
      </div>
      <div class="wall-row"><span>EOD Close (Obs):</span> <b>₹${w.data.eod_premium}</b></div>
      <div class="wall-row"><span>Est. Entry (Est):</span> <b>₹${w.data.est_entry_low} – ₹${w.data.est_entry_high}</b></div>
      <div class="wall-row"><span>Danger Prem (Calc):</span> <b class="danger-txt">₹${w.data.danger_premium}</b></div>
      <div class="wall-row"><span>Danger Spot (Calc):</span> <b class="danger-txt">${w.data.danger_spot}</b></div>
      <div class="wall-rule">${w.data.confirmation_rule}</div>
    </div>
  `).join("");

  document.getElementById("gapGrid").innerHTML = report.gap_playbook.map(g => `
    <div class="gap-box">
      <div class="gap-title">${g.title}</div>
      <div class="gap-cond">${g.condition}</div>
      <div class="gap-act">${g.action}</div>
    </div>
  `).join("");

  const tbody = document.getElementById("strikeTbody");
  tbody.innerHTML = report.strike_table.map(s => `
    <tr class="${s.writing_concentration === "High" ? "row-highlight" : ""}">
      <td><b>${s.strike} ${s.option_type}</b><br><small>${s.next_day_role}</small></td>
      <td>₹${s.eod_premium}<br><small class="${s.premium_chg >= 0 ? "pos" : "neg"}">${s.premium_chg >= 0 ? "+" : ""}${s.premium_chg}</small></td>
      <td>₹${s.est_entry_low}–${s.est_entry_high}<br><small>Conf: ${s.confidence_pct}%</small></td>
      <td>${s.writing_concentration}<br><small>SDI: ${s.sdi_zscore}</small></td>
      <td class="danger-txt"><b>₹${s.danger_premium}</b><br><small>Spot: ${s.danger_spot}</small></td>
      <td>${s.seller_status}<br><small>ΔOI: ${s.chg_in_oi.toLocaleString()}</small></td>
    </tr>
  `).join("");
}

function runAnalysis(selectedDate = null, selectedExpiry = null) {
  const rows = loadStoredRows();
  if (rows.length === 0) {
    document.getElementById("headerMeta").textContent = "Waiting for genuine NSE EOD data";
    document.getElementById("kpiSpot").textContent = "—";
    document.getElementById("kpiAtr").textContent = "—";
    document.getElementById("kpiIv").textContent = "—";
    document.getElementById("kpiCorridor").textContent = "—";
    document.getElementById("regimeBanner").className = "card regime-card regime-warn";
    document.getElementById("regimeVerdict").textContent = "WAIT — DATA REQUIRED";
    document.getElementById("regimeSub").textContent = "No analysis is generated until genuine NSE EOD CSV data is downloaded or imported.";
    document.getElementById("regimeReasons").innerHTML = "";
    document.getElementById("wallsGrid").innerHTML = "";
    document.getElementById("gapGrid").innerHTML = "";
    document.getElementById("strikeTbody").innerHTML = "";
    return;
  }
  try {
    const partRaw = localStorage.getItem(STORAGE_KEY_PART);
    const partSummary = partRaw ? JSON.parse(partRaw) : null;
    const analysisDate = selectedDate || [...new Set(rows.map(r => r.trade_date))].sort().slice(-1)[0];
    const participantForDate = partSummary && partSummary.as_of === analysisDate ? partSummary : null;
    const report = SellerEngine.analyze(rows, participantForDate, { date: analysisDate, expiry: selectedExpiry || null });
    renderReport(report);
  } catch (error) {
    document.getElementById("headerMeta").textContent = "Analysis unavailable — check imported NSE data";
    document.getElementById("kpiSpot").textContent = "—";
    document.getElementById("kpiAtr").textContent = "—";
    document.getElementById("kpiIv").textContent = "—";
    document.getElementById("kpiCorridor").textContent = "—";
    document.getElementById("regimeBanner").className = "card regime-card regime-warn";
    document.getElementById("regimeVerdict").textContent = "ANALYSIS UNAVAILABLE";
    document.getElementById("regimeSub").textContent = error && error.message
      ? error.message
      : "The imported records could not be analyzed. Please verify the NSE CSV and try again.";
    document.getElementById("regimeReasons").innerHTML = "";
    document.getElementById("wallsGrid").innerHTML = "";
    document.getElementById("gapGrid").innerHTML = "";
    document.getElementById("strikeTbody").innerHTML = "";
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  const fileInput = document.getElementById("csvFileInput");
  const statusEl = document.getElementById("importStatus");
  const btnSyncNow = document.getElementById("btnSyncNow");
  const chkAutoSync = document.getElementById("chkAutoSync");
  const nextBadge = document.getElementById("nextScheduleBadge");
  const historyDateSelect = document.getElementById("historyDateSelect");
  const historyExpirySelect = document.getElementById("historyExpirySelect");
  const historyDataMeta = document.getElementById("historyDataMeta");
  const btnDownloadDateCsv = document.getElementById("btnDownloadDateCsv");
  const btnDownloadExpiryCsv = document.getElementById("btnDownloadExpiryCsv");
  let selectedHistoryDate = null;
  let selectedHistoryExpiry = null;

  function csvCell(value) {
    const text = value === null || value === undefined ? "" : String(value);
    return /[",\r\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  }

  async function exportCsv(rows, filename) {
    if (!rows.length) { statusEl.textContent = "No records available for this selection."; return; }
    const columns = ["trade_date","expiry_date","strike","option_type","open_price","high_price","low_price","close_price","settle_price","prev_close_price","spot_close","futures_close","oi","chg_in_oi","volume","turnover","vwap","lot_size"];
    const csv = [columns.join(","), ...rows.map(row => columns.map(key => csvCell(row[key])).join(","))].join("\r\n");
    const csvText = "\uFEFF" + csv;
    const nativePlugin = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.NseAutoSync;
    if (nativePlugin && nativePlugin.saveCsv) {
      try {
        const saved = await nativePlugin.saveCsv({ fileName: filename, csvText });
        statusEl.textContent = "Saved " + saved.fileName + " (" + rows.length + " rows) to " + saved.location + ".";
        return;
      } catch (error) {
        statusEl.textContent = "Android file save failed: " + (error && error.message ? error.message : "Unknown error");
        return;
      }
    }
    const blob = new Blob([csvText], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = filename; anchor.style.display = "none";
    document.body.appendChild(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
    statusEl.textContent = "Prepared " + filename + " (" + rows.length + " NIFTY option rows).";
  }

  function refreshHistorySelectors(preferredDate = null, preferredExpiry = null) {
    const rows = loadStoredRows();
    const dates = [...new Set(rows.map(r => r.trade_date).filter(Boolean))].sort().reverse();
    historyDateSelect.innerHTML = dates.map(d => `<option value="${d}">${d}</option>`).join("");
    historyDateSelect.disabled = dates.length === 0;
    if (!dates.length) {
      historyExpirySelect.innerHTML = '<option value="">No expiry data</option>'; historyExpirySelect.disabled = true;
      historyDataMeta.textContent = "Import or sync NSE data to choose a historical date.";
      btnDownloadDateCsv.disabled = true; btnDownloadExpiryCsv.disabled = true; return;
    }
    selectedHistoryDate = dates.includes(preferredDate) ? preferredDate : dates[0];
    historyDateSelect.value = selectedHistoryDate;
    const expiries = SellerEngine.getAvailableExpiries(rows, selectedHistoryDate);
    historyExpirySelect.innerHTML = expiries.map(e => `<option value="${e}">${e}</option>`).join("");
    historyExpirySelect.disabled = expiries.length === 0;
    if (!expiries.length) {
      selectedHistoryExpiry = null; historyDataMeta.textContent = "No future expiry records are available for " + selectedHistoryDate + ".";
      btnDownloadExpiryCsv.disabled = true;
    } else {
      let autoExpiry = null;
      try { autoExpiry = SellerEngine.getDefaultExpiry(rows, selectedHistoryDate); } catch (_) {}
      selectedHistoryExpiry = expiries.includes(preferredExpiry) ? preferredExpiry : (autoExpiry && expiries.includes(autoExpiry) ? autoExpiry : expiries[0]);
      historyExpirySelect.value = selectedHistoryExpiry;
      const dateRows = rows.filter(r => r.trade_date === selectedHistoryDate);
      const expiryRows = dateRows.filter(r => r.expiry_date === selectedHistoryExpiry);
      historyDataMeta.textContent = `${dateRows.length.toLocaleString()} NIFTY records · ${expiries.length} future expiry choices · ${expiryRows.length.toLocaleString()} records for selected expiry. Auto-selected expiry: ${autoExpiry || "unavailable"}.`;
      btnDownloadExpiryCsv.disabled = expiryRows.length === 0;
    }
    btnDownloadDateCsv.disabled = !rows.some(r => r.trade_date === selectedHistoryDate);
  }

  function runSelectedHistoricalAnalysis() {
    selectedHistoryDate = historyDateSelect.value || null;
    selectedHistoryExpiry = historyExpirySelect.value || null;
    runAnalysis(selectedHistoryDate, selectedHistoryExpiry);
    refreshHistorySelectors(selectedHistoryDate, selectedHistoryExpiry);
  }

  async function triggerAutoDownload(force = false) {
    btnSyncNow.disabled = true;
    btnSyncNow.textContent = "Syncing NSE...";
    try {
      const res = await NSEAutoDownloader.syncNow({
        lookbackDays: 5,
        force,
        onProgress: (msg) => { statusEl.textContent = msg; }
      });
      const added = ingestSyncPayload(res);
      const datesCount = new Set(loadStoredRows().map(r => r.trade_date)).size;
      statusEl.textContent = added > 0
        ? `${res.statusMessage} (${added} NIFTY rows merged | ${datesCount} sessions stored)`
        : res.statusMessage;
      refreshHistorySelectors();
      runAnalysis();
    } catch (error) {
      statusEl.textContent = "NSE EOD sync failed: " + (error && error.message ? error.message : "Unknown error") + ". You can retry or import the official CSV manually.";
    } finally {
      btnSyncNow.disabled = false;
      btnSyncNow.textContent = "Sync NSE EOD Now";
    }
  }

  // 1. Ingest any EOD files already downloaded by the 6:15 PM IST background worker
  const pending = await NSEAutoDownloader.consumeBackgroundQueue();
  const bgAdded = ingestSyncPayload(pending);
  refreshHistorySelectors();
  runAnalysis();

  // 2. Load schedule & auto-sync state
  const st = await NSEAutoDownloader.getStatus();
  chkAutoSync.checked = st.enabled;
  nextBadge.textContent = st.enabled ? `Next: ${st.nextScheduledIst}` : "Auto-Sync Off";

  if (bgAdded > 0) {
    statusEl.textContent = `Loaded ${bgAdded} background-synced NIFTY EOD records (${st.lastSyncIst}).`;
  } else if (st.enabled) {
    await triggerAutoDownload(false);
  } else {
    statusEl.textContent = "Auto-Sync disabled. Tap 'Sync NSE EOD Now' or 'Import CSVs'.";
  }

  chkAutoSync.addEventListener("change", async () => {
    const updated = await NSEAutoDownloader.setAutoSyncEnabled(chkAutoSync.checked);
    nextBadge.textContent = updated.enabled ? `Next: ${updated.nextScheduledIst}` : "Auto-Sync Off";
    statusEl.textContent = updated.enabled
      ? `Daily 6:15 PM IST Auto-Sync enabled (${updated.nextScheduledIst}).`
      : "Daily 6:15 PM IST Auto-Sync paused.";
  });

  btnSyncNow.addEventListener("click", () => triggerAutoDownload(true));

  historyDateSelect.addEventListener("change", () => {
    selectedHistoryDate = historyDateSelect.value;
    refreshHistorySelectors(selectedHistoryDate, null);
    runSelectedHistoricalAnalysis();
  });
  historyExpirySelect.addEventListener("change", runSelectedHistoricalAnalysis);
  btnDownloadDateCsv.addEventListener("click", () => {
    const rows = loadStoredRows().filter(r => r.trade_date === historyDateSelect.value);
    exportCsv(rows, `NIFTY_EOD_${historyDateSelect.value}_ALL_EXPIRIES.csv`);
  });
  btnDownloadExpiryCsv.addEventListener("click", () => {
    const date = historyDateSelect.value, expiry = historyExpirySelect.value;
    const rows = loadStoredRows().filter(r => r.trade_date === date && r.expiry_date === expiry);
    exportCsv(rows, `NIFTY_EOD_${date}_EXPIRY_${expiry}.csv`);
  });

  fileInput.addEventListener("change", async (evt) => {
    const files = Array.from(evt.target.files || []);
    if (files.length === 0) return;

    statusEl.textContent = `Parsing ${files.length} NSE EOD file(s)...`;
    let existing = loadStoredRows();
    let addedRecords = 0;

    for (const file of files) {
      const text = await file.text();
      if (file.name.toLowerCase().includes("participant")) {
        const part = NSEParser.parseParticipantCSV(text, file.name);
        if (part) localStorage.setItem(STORAGE_KEY_PART, JSON.stringify(part));
      } else {
        const parsed = NSEParser.parseBhavcopyCSV(text, "NIFTY", 75);
        if (parsed.length > 0) {
          existing = mergeRows(existing, parsed);
          addedRecords += parsed.length;
        }
      }
    }

    const saved = saveStoredRows(existing);
    const datesCount = new Set(saved.map(r => r.trade_date)).size;
    statusEl.textContent = `Imported ${addedRecords} NIFTY records. Rolling DB: ${datesCount} trading sessions.`;
    refreshHistorySelectors();
    runAnalysis();
    fileInput.value = "";
  });


  document.getElementById("btnClearDb").addEventListener("click", async () => {
    localStorage.removeItem(STORAGE_KEY_ROWS);
    localStorage.removeItem(STORAGE_KEY_PART);
    try {
      const nativeQueueCleared = await NSEAutoDownloader.clearSyncData();
      statusEl.textContent = nativeQueueCleared
        ? "Local EOD history and pending Android sync data cleared. Import or sync genuine NSE data to begin."
        : "Local EOD history cleared. Import or sync genuine NSE data to begin.";
    } catch (error) {
      statusEl.textContent = "Local history cleared, but pending Android sync data could not be cleared: " + (error && error.message ? error.message : "Unknown error");
    }
    refreshHistorySelectors();
    runAnalysis();
  });
});

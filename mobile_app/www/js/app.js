const STORAGE_KEY_ROWS = "nifty_eod_rolling_rows_v1";
const STORAGE_KEY_PART = "nifty_eod_participant_v1";

function loadStoredRows() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_ROWS);
    return raw ? JSON.parse(raw) : [];
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

function runAnalysis() {
  let rows = loadStoredRows();
  if (rows.length === 0) {
    rows = saveStoredRows(NSEParser.generateDemo22Sessions());
  }
  const partRaw = localStorage.getItem(STORAGE_KEY_PART);
  const partSummary = partRaw ? JSON.parse(partRaw) : null;
  const report = SellerEngine.analyze(rows, partSummary);
  renderReport(report);
}

document.addEventListener("DOMContentLoaded", async () => {
  const fileInput = document.getElementById("csvFileInput");
  const statusEl = document.getElementById("importStatus");
  const btnSyncNow = document.getElementById("btnSyncNow");
  const chkAutoSync = document.getElementById("chkAutoSync");
  const nextBadge = document.getElementById("nextScheduleBadge");

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
      runAnalysis();
    } finally {
      btnSyncNow.disabled = false;
      btnSyncNow.textContent = "Sync NSE EOD Now";
    }
  }

  // 1. Ingest any EOD files already downloaded by the 6:15 PM IST background worker
  const pending = await NSEAutoDownloader.consumeBackgroundQueue();
  const bgAdded = ingestSyncPayload(pending);
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
    runAnalysis();
    fileInput.value = "";
  });

  document.getElementById("btnLoadDemo").addEventListener("click", () => {
    const demo = NSEParser.generateDemo22Sessions();
    saveStoredRows(demo);
    localStorage.removeItem(STORAGE_KEY_PART);
    statusEl.textContent = "Loaded 22-session sample NIFTY EOD dataset.";
    runAnalysis();
  });

  document.getElementById("btnClearDb").addEventListener("click", () => {
    localStorage.removeItem(STORAGE_KEY_ROWS);
    localStorage.removeItem(STORAGE_KEY_PART);
    statusEl.textContent = "Cleared local EOD history. Showing sample baseline.";
    runAnalysis();
  });
});

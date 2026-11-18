const NSEAutoDownloader = (() => {
  const PREF_AUTO_ENABLED = "nifty_auto_sync_enabled_v1";

  function getNativePlugin() {
    return window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.NseAutoSync
      ? window.Capacitor.Plugins.NseAutoSync
      : null;
  }

  function isAutoSyncEnabled() {
    const val = localStorage.getItem(PREF_AUTO_ENABLED);
    return val === null ? true : val === "true";
  }

  async function setAutoSyncEnabled(enabled) {
    localStorage.setItem(PREF_AUTO_ENABLED, String(Boolean(enabled)));
    const plugin = getNativePlugin();
    if (plugin) {
      return await plugin.configureSchedule({ enabled: Boolean(enabled) });
    }
    return { enabled: Boolean(enabled), nextScheduledIst: enabled ? "06:15 PM IST (Android APK)" : "Disabled" };
  }

  async function getStatus() {
    const plugin = getNativePlugin();
    if (plugin) {
      return await plugin.getSyncStatus();
    }
    return {
      enabled: isAutoSyncEnabled(),
      lastSyncIst: "Browser Mode",
      nextScheduledIst: "06:15 PM IST (Active inside Android APK)"
    };
  }

  async function consumeBackgroundQueue() {
    const plugin = getNativePlugin();
    if (!plugin) return null;
    return await plugin.consumePendingSync();
  }

  async function syncNow({ lookbackDays = 5, force = false, onProgress = null } = {}) {
    const plugin = getNativePlugin();
    let listenerHandle = null;

    if (plugin) {
      if (onProgress && plugin.addListener) {
        listenerHandle = await plugin.addListener("syncProgress", (ev) => {
          if (ev && ev.message) onProgress(ev.message);
        });
      }
      try {
        return await plugin.syncNow({ lookbackDays, force });
      } finally {
        if (listenerHandle && listenerHandle.remove) listenerHandle.remove();
      }
    }

    return {
      syncedDates: [],
      bhavCsvList: [],
      participantCsv: "",
      participantFileName: "",
      statusMessage: "Direct browser blocked by NSE CORS/Akamai. Build the Android APK for native session auto-sync, or use 'Import CSVs' below."
    };
  }

  return {
    isAutoSyncEnabled,
    setAutoSyncEnabled,
    getStatus,
    consumeBackgroundQueue,
    syncNow
  };
})();

package com.nifty.sellerintel;

import android.content.Context;
import android.content.SharedPreferences;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import org.json.JSONObject;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

@CapacitorPlugin(name = "NseAutoSync")
public class NseAutoSyncPlugin extends Plugin {
    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    @PluginMethod
    public void syncNow(PluginCall call) {
        int lookbackDays = call.getInt("lookbackDays", 5);
        boolean force = call.getBoolean("force", false);
        Context ctx = getContext();

        executor.execute(() -> {
            NseSessionFetcher.SyncResult res = NseSessionFetcher.fetchLatestEod(ctx, lookbackDays, force, msg -> {
                JSObject prog = new JSObject();
                prog.put("message", msg);
                notifyListeners("syncProgress", prog);
            });

            JSObject ret = new JSObject();
            JSArray datesArr = new JSArray();
            for (String d : res.syncedDates) datesArr.put(d);

            JSArray csvArr = new JSArray();
            for (String c : res.bhavCsvPayloads) csvArr.put(c);

            ret.put("syncedDates", datesArr);
            ret.put("bhavCsvList", csvArr);
            ret.put("participantCsv", res.participantCsv);
            ret.put("participantFileName", res.participantFileName);
            ret.put("lastSyncIst", res.lastSyncIst);
            ret.put("statusMessage", res.statusMessage);
            call.resolve(ret);
        });
    }

    @PluginMethod
    public void consumePendingSync(PluginCall call) {
        JSONObject pending = NseSessionFetcher.consumePendingSync(getContext());
        try {
            call.resolve(JSObject.fromJSONObject(pending));
        } catch (Exception e) {
            call.resolve(new JSObject());
        }
    }

    @PluginMethod
    public void configureSchedule(PluginCall call) {
        boolean enabled = call.getBoolean("enabled", true);
        String nextStr = NseSyncWorker.scheduleDaily615PmIst(getContext(), enabled);
        JSObject ret = new JSObject();
        ret.put("enabled", enabled);
        ret.put("nextScheduledIst", nextStr);
        call.resolve(ret);
    }

    @PluginMethod
    public void getSyncStatus(PluginCall call) {
        SharedPreferences prefs = getContext().getSharedPreferences(NseSessionFetcher.PREFS_NAME, Context.MODE_PRIVATE);
        boolean enabled = prefs.getBoolean("auto_sync_enabled", true);
        String nextStr = prefs.getString("next_scheduled_ist", "");
        if (enabled && nextStr.isEmpty()) {
            nextStr = NseSyncWorker.scheduleDaily615PmIst(getContext(), true);
        }
        JSObject ret = new JSObject();
        ret.put("enabled", enabled);
        ret.put("lastSyncIst", prefs.getString("last_sync_ist", "Never"));
        ret.put("lastSyncStatus", prefs.getString("last_sync_status", "Ready"));
        ret.put("nextScheduledIst", nextStr);
        call.resolve(ret);
    }
}

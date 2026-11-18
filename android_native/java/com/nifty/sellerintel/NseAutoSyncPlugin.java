package com.nifty.sellerintel;

import android.content.Context;
import android.content.SharedPreferences;
import android.content.ContentValues;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

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
    public void clearSyncData(PluginCall call) {
        Context context = getContext();
        SharedPreferences prefs = context.getSharedPreferences(NseSessionFetcher.PREFS_NAME, Context.MODE_PRIVATE);
        boolean autoSyncEnabled = prefs.getBoolean("auto_sync_enabled", true);
        androidx.work.WorkManager.getInstance(context).cancelUniqueWork(NseSyncWorker.UNIQUE_WORK_NAME);
        NseSessionFetcher.clearLocalSyncData(context);
        if (autoSyncEnabled) {
            NseSyncWorker.scheduleDaily615PmIst(context, true);
        }
        call.resolve();
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
    public void saveCsv(PluginCall call) {
        String fileName = call.getString("fileName", "NIFTY_EOD_export.csv");
        String csvText = call.getString("csvText", "");
        if (csvText.isEmpty()) {
            call.reject("CSV content is empty.");
            return;
        }
        fileName = fileName.replaceAll("[^A-Za-z0-9._-]", "_");
        if (!fileName.toLowerCase().endsWith(".csv")) fileName += ".csv";
        final String safeName = fileName;
        final String content = csvText;
        executor.execute(() -> {
            try {
                Uri savedUri;
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    ContentValues values = new ContentValues();
                    values.put(MediaStore.Downloads.DISPLAY_NAME, safeName);
                    values.put(MediaStore.Downloads.MIME_TYPE, "text/csv");
                    values.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/NiftySellerIntel");
                    values.put(MediaStore.Downloads.IS_PENDING, 1);
                    Uri collection = MediaStore.Downloads.EXTERNAL_CONTENT_URI;
                    savedUri = getContext().getContentResolver().insert(collection, values);
                    if (savedUri == null) throw new IllegalStateException("Android could not create the download file.");
                    try (OutputStream out = getContext().getContentResolver().openOutputStream(savedUri)) {
                        if (out == null) throw new IllegalStateException("Could not open the download file.");
                        out.write(content.getBytes(StandardCharsets.UTF_8));
                        out.flush();
                    }
                    ContentValues ready = new ContentValues();
                    ready.put(MediaStore.Downloads.IS_PENDING, 0);
                    getContext().getContentResolver().update(savedUri, ready, null, null);
                } else {
                    File dir = getContext().getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
                    if (dir == null) throw new IllegalStateException("App download folder is unavailable.");
                    if (!dir.exists() && !dir.mkdirs()) throw new IllegalStateException("Could not create download folder.");
                    File outFile = new File(dir, safeName);
                    try (FileOutputStream out = new FileOutputStream(outFile)) {
                        out.write(content.getBytes(StandardCharsets.UTF_8));
                        out.flush();
                    }
                    savedUri = Uri.fromFile(outFile);
                }
                JSObject result = new JSObject();
                result.put("fileName", safeName);
                result.put("uri", savedUri.toString());
                result.put("location", Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
                    ? "Downloads/NiftySellerIntel/" + safeName : "App Downloads/" + safeName);
                call.resolve(result);
            } catch (Exception e) {
                call.reject("CSV download failed: " + e.getMessage(), e);
            }
        });
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

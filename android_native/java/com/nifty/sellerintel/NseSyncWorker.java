package com.nifty.sellerintel;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;

import androidx.annotation.NonNull;
import androidx.core.app.NotificationCompat;
import androidx.work.Constraints;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.WorkManager;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import java.time.Duration;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.concurrent.TimeUnit;

public class NseSyncWorker extends Worker {
    public static final String UNIQUE_WORK_NAME = "NSE_EOD_DAILY_615PM_IST";
    private static final String CHANNEL_ID = "nse_eod_sync_channel";

    public NseSyncWorker(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    @NonNull
    @Override
    public Result doWork() {
        Context ctx = getApplicationContext();
        SharedPreferences prefs = ctx.getSharedPreferences(NseSessionFetcher.PREFS_NAME, Context.MODE_PRIVATE);
        boolean enabled = prefs.getBoolean("auto_sync_enabled", true);

        if (enabled) {
            NseSessionFetcher.SyncResult res = NseSessionFetcher.fetchLatestEod(ctx, 5, false, null);
            if (!res.syncedDates.isEmpty()) {
                NseSessionFetcher.enqueueBackgroundSyncResult(ctx, res);
                showNotification(ctx, "NIFTY EOD Auto-Synced", res.statusMessage);
            }
            scheduleDaily615PmIst(ctx, true);
        }
        return Result.success();
    }

    public static String scheduleDaily615PmIst(Context context, boolean enabled) {
        SharedPreferences prefs = context.getSharedPreferences(NseSessionFetcher.PREFS_NAME, Context.MODE_PRIVATE);
        prefs.edit().putBoolean("auto_sync_enabled", enabled).apply();

        WorkManager wm = WorkManager.getInstance(context);
        if (!enabled) {
            wm.cancelUniqueWork(UNIQUE_WORK_NAME);
            return "Disabled";
        }

        ZoneId ist = ZoneId.of("Asia/Kolkata");
        ZonedDateTime now = ZonedDateTime.now(ist);
        ZonedDateTime nextRun = now.withHour(18).withMinute(15).withSecond(0).withNano(0);
        if (!nextRun.isAfter(now)) {
            nextRun = nextRun.plusDays(1);
        }

        long delayMs = Math.max(5000L, Duration.between(now, nextRun).toMillis());
        Constraints constraints = new Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build();

        OneTimeWorkRequest req = new OneTimeWorkRequest.Builder(NseSyncWorker.class)
            .setInitialDelay(delayMs, TimeUnit.MILLISECONDS)
            .setConstraints(constraints)
            .build();

        wm.enqueueUniqueWork(UNIQUE_WORK_NAME, ExistingWorkPolicy.REPLACE, req);
        String nextStr = nextRun.format(DateTimeFormatter.ofPattern("dd MMM, hh:mm a")) + " IST";
        prefs.edit().putString("next_scheduled_ist", nextStr).apply();
        return nextStr;
    }

    private static void showNotification(Context ctx, String title, String body) {
        try {
            NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm == null) return;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                NotificationChannel ch = new NotificationChannel(CHANNEL_ID, "NSE EOD Auto-Sync", NotificationManager.IMPORTANCE_LOW);
                nm.createNotificationChannel(ch);
            }
            NotificationCompat.Builder nb = new NotificationCompat.Builder(ctx, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_sys_download_done)
                .setContentTitle(title)
                .setContentText(body)
                .setAutoCancel(true);
            nm.notify(1815, nb.build());
        } catch (Exception ignored) {
        }
    }
}

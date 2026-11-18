package com.nifty.sellerintel;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;

public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        SharedPreferences prefs = context.getSharedPreferences(NseSessionFetcher.PREFS_NAME, Context.MODE_PRIVATE);
        if (prefs.getBoolean("auto_sync_enabled", true)) {
            NseSyncWorker.scheduleDaily615PmIst(context, true);
        }
    }
}

package com.nifty.sellerintel;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(NseAutoSyncPlugin.class);
        super.onCreate(savedInstanceState);
        NseSyncWorker.scheduleDaily615PmIst(
            this,
            getSharedPreferences(NseSessionFetcher.PREFS_NAME, MODE_PRIVATE).getBoolean("auto_sync_enabled", true)
        );
    }
}

package com.nifty.sellerintel;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;
import android.webkit.CookieManager;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.BufferedReader;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.CookieHandler;
import java.net.CookiePolicy;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

public class NseSessionFetcher {
    public static final String PREFS_NAME = "NseAutoSyncPrefs";
    private static final String USER_AGENT =
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36";

    public interface ProgressListener {
        void onProgress(String message);
    }

    public static class SyncResult {
        public List<String> syncedDates = new ArrayList<>();
        public List<String> bhavCsvPayloads = new ArrayList<>();
        public String participantCsv = "";
        public String participantFileName = "";
        public String statusMessage = "";
        public String lastSyncIst = "";
    }

    public static SyncResult fetchLatestEod(Context context, int lookbackDays, boolean force, ProgressListener listener) {
        SyncResult result = new SyncResult();
        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        Set<String> alreadySynced = new HashSet<>(prefs.getStringSet("synced_dates_set", new HashSet<>()));

        try {
            if (listener != null) listener.onProgress("Warming NSE India session cookies...");
            java.net.CookieManager netCookies = new java.net.CookieManager(null, CookiePolicy.ACCEPT_ALL);
            CookieHandler.setDefault(netCookies);

            warmUpSessionHttp();
            String webCookies = warmUpSessionWebView(context);

            List<LocalDate> candidateDates = getRecentTradingDates(Math.max(1, Math.min(lookbackDays, 10)));
            String latestPartCsv = "";
            String latestPartName = "";
            int attemptedDates = 0;

            for (LocalDate dt : candidateDates) {
                String isoDate = dt.format(DateTimeFormatter.ISO_LOCAL_DATE);
                if (!force && alreadySynced.contains(isoDate)) {
                    continue;
                }
                attemptedDates++;

                String yyyymmdd = dt.format(DateTimeFormatter.ofPattern("yyyyMMdd"));
                String ddmmyyyy = dt.format(DateTimeFormatter.ofPattern("ddMMyyyy"));

                if (listener != null) listener.onProgress("Downloading NSE F&O BhavCopy (" + isoDate + ")...");
                String bhavUrl = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_" + yyyymmdd + "_F_0000.csv.zip";
                byte[] zipBytes = downloadBytes(bhavUrl, webCookies);

                if (zipBytes != null && zipBytes.length > 100) {
                    String filteredNiftyCsv = extractAndFilterNiftyCsv(zipBytes);
                    if (!filteredNiftyCsv.isEmpty()) {
                        result.bhavCsvPayloads.add(filteredNiftyCsv);
                        result.syncedDates.add(isoDate);
                        alreadySynced.add(isoDate);
                    }
                }

                if (latestPartCsv.isEmpty()) {
                    String partUrl = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_" + ddmmyyyy + ".csv";
                    byte[] partBytes = downloadBytes(partUrl, webCookies);
                    if (partBytes != null && partBytes.length > 50) {
                        String text = new String(partBytes, StandardCharsets.UTF_8);
                        if (text.contains("Client Type")) {
                            latestPartCsv = text;
                            latestPartName = "fao_participant_oi_" + ddmmyyyy + ".csv";
                        }
                    }
                }
            }

            result.participantCsv = latestPartCsv;
            result.participantFileName = latestPartName;

            ZonedDateTime nowIst = ZonedDateTime.now(ZoneId.of("Asia/Kolkata"));
            result.lastSyncIst = nowIst.format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")) + " IST";

            if (!result.syncedDates.isEmpty()) {
                result.statusMessage = "Synced " + result.syncedDates.size() + " NSE EOD session(s): " + String.join(", ", result.syncedDates);
            } else if (attemptedDates == 0) {
                result.statusMessage = "Already up to date with latest NSE EOD (" + result.lastSyncIst + ")";
            } else {
                result.statusMessage = "No NSE BhavCopy files were downloaded for " + attemptedDates
                    + " attempted trading date(s). NSE may not have published the files yet, the dates may be exchange holidays, "
                    + "or the request may have been blocked. Check the date range or import the official CSV manually.";
            }

            prefs.edit()
                .putStringSet("synced_dates_set", alreadySynced)
                .putString("last_sync_ist", result.lastSyncIst)
                .putString("last_sync_status", result.statusMessage)
                .apply();

        } catch (Exception e) {
            result.statusMessage = "NSE Auto-Sync failed: " + e.getMessage() + " (Use manual CSV import if market holiday)";
            prefs.edit().putString("last_sync_status", result.statusMessage).apply();
        }
        return result;
    }

    public static void enqueueBackgroundSyncResult(Context context, SyncResult res) {
        if (res.bhavCsvPayloads.isEmpty() && res.participantCsv.isEmpty()) return;
        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        try {
            JSONArray existingArr = new JSONArray(prefs.getString("pending_bhav_json", "[]"));
            for (String csv : res.bhavCsvPayloads) {
                existingArr.put(csv);
            }
            SharedPreferences.Editor ed = prefs.edit().putString("pending_bhav_json", existingArr.toString());
            if (!res.participantCsv.isEmpty()) {
                ed.putString("pending_part_csv", res.participantCsv);
                ed.putString("pending_part_name", res.participantFileName);
            }
            ed.apply();
        } catch (Exception ignored) {
        }
    }

    public static JSONObject consumePendingSync(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        JSONObject out = new JSONObject();
        try {
            String bhavJson = prefs.getString("pending_bhav_json", "[]");
            String partCsv = prefs.getString("pending_part_csv", "");
            String partName = prefs.getString("pending_part_name", "");
            out.put("bhavCsvList", new JSONArray(bhavJson));
            out.put("participantCsv", partCsv);
            out.put("participantFileName", partName);
            out.put("lastSyncIst", prefs.getString("last_sync_ist", ""));
            out.put("statusMessage", prefs.getString("last_sync_status", ""));

            prefs.edit()
                .remove("pending_bhav_json")
                .remove("pending_part_csv")
                .remove("pending_part_name")
                .apply();
        } catch (Exception ignored) {
        }
        return out;
    }

    private static void warmUpSessionHttp() {
        String[] seedUrls = new String[]{
            "https://www.nseindia.com",
            "https://www.nseindia.com/all-reports-derivatives"
        };
        for (String u : seedUrls) {
            HttpURLConnection conn = null;
            try {
                conn = (HttpURLConnection) new URL(u).openConnection();
                conn.setRequestMethod("GET");
                conn.setConnectTimeout(12000);
                conn.setReadTimeout(12000);
                conn.setRequestProperty("User-Agent", USER_AGENT);
                conn.setRequestProperty("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8");
                conn.setRequestProperty("Accept-Language", "en-IN,en-US;q=0.9,en;q=0.8");
                conn.getResponseCode();
            } catch (Exception ignored) {
            } finally {
                if (conn != null) conn.disconnect();
            }
        }
    }

    private static String warmUpSessionWebView(Context context) {
        final String[] cookieHolder = new String[]{""};
        final CountDownLatch latch = new CountDownLatch(1);
        new Handler(Looper.getMainLooper()).post(() -> {
            try {
                CookieManager cm = CookieManager.getInstance();
                cm.setAcceptCookie(true);
                WebView webView = new WebView(context.getApplicationContext());
                WebSettings ws = webView.getSettings();
                ws.setJavaScriptEnabled(true);
                ws.setDomStorageEnabled(true);
                ws.setUserAgentString(USER_AGENT);
                webView.setWebViewClient(new WebViewClient() {
                    @Override
                    public void onPageFinished(WebView view, String url) {
                        String c = cm.getCookie("https://www.nseindia.com");
                        if (c != null && !c.isEmpty()) {
                            cookieHolder[0] = c;
                        }
                        latch.countDown();
                        view.destroy();
                    }
                });
                webView.loadUrl("https://www.nseindia.com/all-reports-derivatives");
            } catch (Exception e) {
                latch.countDown();
            }
        });
        try {
            latch.await(8, TimeUnit.SECONDS);
        } catch (InterruptedException ignored) {
        }
        return cookieHolder[0];
    }

    private static byte[] downloadBytes(String urlStr, String extraCookies) {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(urlStr).openConnection();
            conn.setRequestMethod("GET");
            conn.setInstanceFollowRedirects(true);
            conn.setConnectTimeout(15000);
            conn.setReadTimeout(20000);
            conn.setRequestProperty("User-Agent", USER_AGENT);
            conn.setRequestProperty("Accept", "*/*");
            conn.setRequestProperty("Accept-Language", "en-IN,en-US;q=0.9,en;q=0.8");
            conn.setRequestProperty("Referer", "https://www.nseindia.com/all-reports-derivatives");
            if (extraCookies != null && !extraCookies.isEmpty()) {
                conn.setRequestProperty("Cookie", extraCookies);
            }

            int code = conn.getResponseCode();
            if (code != 200) return null;

            try (InputStream is = new BufferedInputStream(conn.getInputStream());
                 ByteArrayOutputStream baos = new ByteArrayOutputStream()) {
                byte[] buf = new byte[8192];
                int n;
                while ((n = is.read(buf)) != -1) {
                    baos.write(buf, 0, n);
                }
                return baos.toByteArray();
            }
        } catch (Exception e) {
            return null;
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private static String extractAndFilterNiftyCsv(byte[] zipBytes) {
        try (ZipInputStream zis = new ZipInputStream(new ByteArrayInputStream(zipBytes))) {
            ZipEntry entry;
            while ((entry = zis.getNextEntry()) != null) {
                if (!entry.isDirectory() && entry.getName().toLowerCase().endsWith(".csv")) {
                    BufferedReader reader = new BufferedReader(new InputStreamReader(zis, StandardCharsets.UTF_8));
                    String header = reader.readLine();
                    if (header == null) return "";
                    StringBuilder sb = new StringBuilder();
                    sb.append(header).append("\n");
                    String line;
                    int count = 0;
                    while ((line = reader.readLine()) != null) {
                        if (line.contains(",NIFTY,") || line.contains("\"NIFTY\"")) {
                            sb.append(line).append("\n");
                            count++;
                        }
                    }
                    return count > 0 ? sb.toString() : "";
                }
            }
        } catch (Exception ignored) {
        }
        return "";
    }

    public static List<LocalDate> getRecentTradingDates(int count) {
        ZonedDateTime nowIst = ZonedDateTime.now(ZoneId.of("Asia/Kolkata"));
        LocalDate cursor = nowIst.toLocalDate();
        // NSE EOD UDiFF Bhavcopy publishes around 18:00 IST
        if (nowIst.toLocalTime().isBefore(LocalTime.of(18, 0))) {
            cursor = cursor.minusDays(1);
        }
        List<LocalDate> dates = new ArrayList<>();
        while (dates.size() < count) {
            DayOfWeek dow = cursor.getDayOfWeek();
            if (dow != DayOfWeek.SATURDAY && dow != DayOfWeek.SUNDAY) {
                dates.add(cursor);
            }
            cursor = cursor.minusDays(1);
        }
        return dates;
    }
}

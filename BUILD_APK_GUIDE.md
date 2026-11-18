# Step-by-Step Guide: Building the Standalone Android `.apk` (With NSE EOD Auto-Download)

This project includes a complete **auto-syncing + offline-capable mobile application** in `mobile_app/www/` wrapped with **Capacitor 8 (`@capacitor/android`)** and native Android background sync classes in `android_native/`.

## What's Included in v1.1.0 (Auto-Download Upgrade)
- **Native NSE Session Cookie Warmup (`NseSessionFetcher.java`)**: Acquires `nseindia.com` session cookies via `CookieManager` + headless `WebView` cookie jar, downloads `BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip` and `fao_participant_oi_DDMMYYYY.csv` for missing recent trading sessions (up to 5 trading days lookback), unzips in memory, and filters `NIFTY` rows.
- **Daily 6:15 PM IST Background Auto-Sync (`NseSyncWorker.java` + `BootReceiver.java`)**: Schedules a daily `WorkManager` job at **18:15 IST** (persisting across device reboots) and queues synced EOD sessions for automatic ingestion on app launch.
- **One-Tap `Sync NSE EOD Now` + Manual CSV Fallback**: Tap **Sync NSE EOD Now** anytime, toggle **Auto-Sync NSE EOD**, or use **Import CSVs** manually if needed.

## Prerequisites
1. **Node.js v20+** and **npm**
2. **JDK 21** (`JAVA_HOME` configured)
3. **Android Studio** with **Android SDK (API 34+)** and `ANDROID_HOME` configured

## Step 1: Install Capacitor Dependencies
Open a terminal in the root folder of this extracted ZIP (`nifty_option_seller_intelligence/`) and run:
```bash
npm install
```

## Step 2: Generate & Auto-Configure the Native Android Project
```bash
npx cap add android
npm run sync
```
> `npm run sync` runs `npx cap sync android` and executes `scripts/configure-android.js` to automatically copy the Java auto-sync classes (`NseSessionFetcher`, `NseSyncWorker`, `NseAutoSyncPlugin`, `BootReceiver`, `MainActivity`), inject required permissions (`INTERNET`, `ACCESS_NETWORK_STATE`, `RECEIVE_BOOT_COMPLETED`, `POST_NOTIFICATIONS`), and add `androidx.work:work-runtime:2.9.1`.

## Step 3: Build the Installable `.apk`

### Option A — Build Debug APK via Command Line (Fastest)
```bash
npm run build:apk
```
Your installable `.apk` will be created at:
`android/app/build/outputs/apk/debug/app-debug.apk`

### Option B — Build via Android Studio GUI
```bash
npx cap open android
```
Inside Android Studio, wait for Gradle sync to finish, then click:
**Build > Build Bundle(s) / APK(s) > Build APK(s)**.

## Daily Workflow on Android
1. Install `app-debug.apk` on your Android phone.
2. Launch **NIFTY Seller Intel** — with **Auto-Sync NSE EOD** toggled ON, the app automatically fetches missing recent EOD BhavCopy + Participant OI reports and schedules a daily **6:15 PM IST** background sync.
3. All Forward Black-Scholes-Merton IV solving, Greeks, BSM Spot Danger inversion, 5D/22D intensity scoring, Sideways No-Trade warnings, and 9:15 AM Opening Gap Playbooks compute locally on-device.

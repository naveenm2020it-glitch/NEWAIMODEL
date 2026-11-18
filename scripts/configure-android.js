const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const androidDir = path.join(root, "android");
if (!fs.existsSync(androidDir)) {
  console.log("[configure-android] android/ folder not found yet. Run 'npx cap add android' first.");
  process.exit(0);
}

// 1. Copy native Java files into android/app/src/main/java/com/nifty/sellerintel/
const srcJavaDir = path.join(root, "android_native", "java", "com", "nifty", "sellerintel");
const destJavaDir = path.join(androidDir, "app", "src", "main", "java", "com", "nifty", "sellerintel");
fs.mkdirSync(destJavaDir, { recursive: true });

for (const file of fs.readdirSync(srcJavaDir)) {
  if (file.endsWith(".java")) {
    fs.copyFileSync(path.join(srcJavaDir, file), path.join(destJavaDir, file));
  }
}

// 2. Inject permissions & BootReceiver into AndroidManifest.xml
const manifestPath = path.join(androidDir, "app", "src", "main", "AndroidManifest.xml");
let manifest = fs.readFileSync(manifestPath, "utf8");

const requiredPerms = [
  '<uses-permission android:name="android.permission.INTERNET" />',
  '<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />',
  '<uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />',
  '<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />'
];

for (const perm of requiredPerms) {
  if (!manifest.includes(perm)) {
    manifest = manifest.replace("<application", `${perm}\n    <application`);
  }
}

const receiverXml = `
        <receiver
            android:name=".BootReceiver"
            android:enabled="true"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.BOOT_COMPLETED" />
                <action android:name="android.intent.action.MY_PACKAGE_REPLACED" />
            </intent-filter>
        </receiver>`;

if (!manifest.includes(".BootReceiver")) {
  manifest = manifest.replace("</application>", `${receiverXml}\n    </application>`);
}
fs.writeFileSync(manifestPath, manifest, "utf8");

// 3. Add AndroidX WorkManager dependency to android/app/build.gradle
const appGradlePath = path.join(androidDir, "app", "build.gradle");
let gradle = fs.readFileSync(appGradlePath, "utf8");
const workDep = 'implementation "androidx.work:work-runtime:2.9.1"';
if (!gradle.includes("androidx.work:work-runtime")) {
  gradle = gradle.replace(/dependencies\s*\{/, `dependencies {\n    ${workDep}`);
  fs.writeFileSync(appGradlePath, gradle, "utf8");
}

console.log("[configure-android] Successfully wired NSE Auto-Sync native classes, permissions, and WorkManager.");

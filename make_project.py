#!/usr/bin/env python3
"""Shanza Android project generator.
GitHub Actions ye script chala kar poora Android project banata hai,
phir APK build karta hai. index.html isi folder mein honi chahiye."""
import os
import shutil

F = {}

F["settings.gradle.kts"] = r'''pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "Shanza"
include(":app")
'''

F["build.gradle.kts"] = r'''plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
}
'''

F["gradle.properties"] = r'''org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
android.useAndroidX=true
android.nonTransitiveRClass=true
kotlin.code.style=official
'''

F["app/build.gradle.kts"] = r'''plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.shanza.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.shanza.app"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.work:work-runtime-ktx:2.9.0")
    implementation("androidx.webkit:webkit:1.11.0")
}
'''

F["app/src/main/AndroidManifest.xml"] = r'''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />

    <application
        android:allowBackup="true"
        android:label="Shanza"
        android:theme="@android:style/Theme.DeviceDefault.NoActionBar">

        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:windowSoftInputMode="adjustResize"
            android:configChanges="orientation|screenSize|keyboardHidden">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
'''

F["app/src/main/java/com/shanza/app/MainActivity.kt"] = r'''package com.shanza.app

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.webkit.WebViewAssetLoader
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

object Store {
    fun prefs(c: Context): SharedPreferences =
        c.getSharedPreferences("shanza", Context.MODE_PRIVATE)
}

class Bridge(private val ctx: Context) {
    @JavascriptInterface
    fun sync(json: String) {
        Store.prefs(ctx).edit().putString("state", json).apply()
    }

    @JavascriptInterface
    fun getPending(): String {
        return Store.prefs(ctx).getString("pending", "[]") ?: "[]"
    }

    @JavascriptInterface
    fun clearPending() {
        Store.prefs(ctx).edit().putString("pending", "[]").apply()
    }
}

class MainActivity : Activity() {

    private lateinit var web: WebView
    private var fileCb: ValueCallback<Array<Uri>>? = null

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == 77) {
            fileCb?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data))
            fileCb = null
        } else {
            super.onActivityResult(requestCode, resultCode, data)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }

        val loader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()

        web = WebView(this)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.mediaPlaybackRequiresUserGesture = false
        web.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(
                view: WebView?,
                request: WebResourceRequest?
            ): WebResourceResponse? {
                return loader.shouldInterceptRequest(request!!.url)
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                view: WebView?,
                callback: ValueCallback<Array<Uri>>?,
                params: FileChooserParams?
            ): Boolean {
                fileCb?.onReceiveValue(null)
                fileCb = callback
                val intent = params?.createIntent() ?: return false
                return try {
                    startActivityForResult(intent, 77)
                    true
                } catch (e: Exception) {
                    fileCb = null
                    false
                }
            }
        }
        web.addJavascriptInterface(Bridge(this), "Android")
        setContentView(web)
        web.loadUrl("https://appassets.androidplatform.net/assets/index.html")

        val work = PeriodicWorkRequestBuilder<ProactiveWorker>(1, TimeUnit.HOURS).build()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            "shanza_proactive", ExistingPeriodicWorkPolicy.KEEP, work
        )
    }

    override fun onResume() {
        super.onResume()
        Store.prefs(this).edit().putLong("lastActive", System.currentTimeMillis()).apply()
    }

    override fun onPause() {
        super.onPause()
        Store.prefs(this).edit().putLong("lastActive", System.currentTimeMillis()).apply()
    }
}
'''

F["app/src/main/java/com/shanza/app/ProactiveWorker.kt"] = r'''package com.shanza.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.work.Worker
import androidx.work.WorkerParameters
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

class ProactiveWorker(ctx: Context, params: WorkerParameters) : Worker(ctx, params) {

    override fun doWork(): Result {
        try {
            maybeSend()
        } catch (e: Exception) {
            // chup chaap agli baar try karenge
        }
        return Result.success()
    }

    private fun maybeSend() {
        val p = Store.prefs(applicationContext)
        val stateStr = p.getString("state", null) ?: return
        val st = JSONObject(stateStr)
        val key = st.optString("key", "")
        if (key.isEmpty()) return

        val now = System.currentTimeMillis()
        val hour = Calendar.getInstance().get(Calendar.HOUR_OF_DAY)
        if (hour < 9 || hour >= 23) return

        val lastActive = maxOf(p.getLong("lastActive", 0L), st.optLong("last", 0L))
        if (lastActive == 0L) return
        val gapMs = now - lastActive
        if (gapMs < 3 * 3600000L) return
        if (now - p.getLong("lastNotif", 0L) < 3 * 3600000L) return

        val today = SimpleDateFormat("yyyyMMdd", Locale.US).format(Date())
        val count = if (p.getString("day", "") == today) p.getInt("dayCount", 0) else 0
        if (count >= 4) return

        val hours = (gapMs / 3600000L).toInt()
        val gapText = if (hours >= 48) "${hours / 24} din" else "$hours ghante"
        val note = "[App note: user ne $gapText se baat nahi ki aur app band hai. " +
            "Tum khud pehle message bhej rahi ho (notification ke tor par). " +
            "Apne mood aur waqt ke mutabiq 1-2 chhotay jumlay likho: yaad dilao, haal poocho, shikayat ya pyar jataao. " +
            "Is note ka zikar mat karna.]"

        val contents = JSONArray(st.optString("history", "[]"))
        contents.put(
            JSONObject().put("role", "user")
                .put("parts", JSONArray().put(JSONObject().put("text", note)))
        )
        val nowText = SimpleDateFormat("dd/MM/yyyy HH:mm", Locale.US).format(Date())
        val system = st.optString("system", "") + "\nAbhi ka asli waqt: " + nowText

        val models = listOf(st.optString("model", ""), "gemini-2.5-flash", "gemini-flash-latest")
            .filter { it.isNotEmpty() }
            .distinct()

        var reply: String? = null
        for (m in models) {
            try {
                reply = callGemini(m, key, system, contents)
                break
            } catch (e: Exception) {
            }
        }
        if (reply == null) return

        val text = reply
            .replace(Regex("^\\s*\\[mood:[^\\]]*\\]\\s*", RegexOption.IGNORE_CASE), "")
            .replace(Regex("\\[PHOTO\\]", RegexOption.IGNORE_CASE), "")
            .trim()
        if (text.isEmpty()) return

        notifyUser(st.optString("name", "Shanza"), text)

        val pend = JSONArray(p.getString("pending", "[]"))
        pend.put(JSONObject().put("note", note).put("reply", reply).put("at", now))
        p.edit()
            .putString("pending", pend.toString())
            .putLong("lastNotif", now)
            .putString("day", today)
            .putInt("dayCount", count + 1)
            .apply()
    }

    private fun callGemini(model: String, key: String, system: String, contents: JSONArray): String {
        val body = JSONObject()
            .put("system_instruction", JSONObject().put("parts", JSONArray().put(JSONObject().put("text", system))))
            .put("contents", contents)
        val url = URL("https://generativelanguage.googleapis.com/v1beta/models/$model:generateContent?key=$key")
        val c = url.openConnection() as HttpURLConnection
        c.requestMethod = "POST"
        c.connectTimeout = 20000
        c.readTimeout = 40000
        c.doOutput = true
        c.setRequestProperty("Content-Type", "application/json")
        c.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
        if (c.responseCode != 200) throw Exception("HTTP " + c.responseCode)
        val txt = c.inputStream.bufferedReader().use { it.readText() }
        return JSONObject(txt)
            .getJSONArray("candidates").getJSONObject(0)
            .getJSONObject("content").getJSONArray("parts").getJSONObject(0)
            .getString("text")
    }

    private fun notifyUser(name: String, text: String) {
        val ctx = applicationContext
        val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(
            NotificationChannel("shanza_msgs", "Shanza ke messages", NotificationManager.IMPORTANCE_HIGH)
        )
        val intent = Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val pi = PendingIntent.getActivity(
            ctx, 0, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val n = Notification.Builder(ctx, "shanza_msgs")
            .setSmallIcon(android.R.drawable.stat_notify_chat)
            .setContentTitle(name)
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setContentIntent(pi)
            .setAutoCancel(true)
            .build()
        nm.notify(System.currentTimeMillis().toInt(), n)
    }
}
'''

for path, content in F.items():
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

os.makedirs("app/src/main/assets", exist_ok=True)
shutil.copy("index.html", "app/src/main/assets/index.html")
print("Project tayyar:", len(F) + 1, "files")

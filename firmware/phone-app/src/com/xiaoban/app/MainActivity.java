package com.xiaoban.app;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * 小伴 · 手机端（v2）
 *
 * 和 v1 的区别：不再只是个网页壳。
 *   - 内置无障碍服务 → 实时界面树 + 直接点节点（PC 那边调它，毫秒级）
 *   - 内置本地 HTTP 服务 :9123 → PC 通过 Tailscale/局域网直接调手机能力
 *   - 自更新：查 PC 上的版本 → 下载 APK → 拉起安装
 */
public class MainActivity extends Activity {

    // ======== 配置 ========
    private static final String TOKEN = "DVO5BZyPDRRLY_lJ-y-etSZn1UZSkF21guugqD-hz7U";
    private static final String[] CANDIDATES = new String[]{
            "http://127.0.0.1:8770",        // USB 反向转发（adb reverse，最稳）
            "http://100.118.110.25:8770",   // Tailscale（异地）
            "http://172.30.0.217:8770"      // 局域网
    };
    private static final int PROBE_TIMEOUT_MS = 2500;
    private static final String PREF = "xiaoban";
    private static final String KEY_LAST = "last_base";
    // ======================

    private WebView web;
    private TextView status;
    private TextView badge;
    private TextView connBadge;
    private LinearLayout root;
    private AgentLoop agent;
    private LinearLayout offlineView;
    private LinearLayout offlineLog;
    private android.widget.EditText offlineInput;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private volatile boolean destroyed = false;
    private String curBase = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#0f1115"));

        // ---- 顶部状态条（原生，一眼看到能力状态）----
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setBackgroundColor(Color.parseColor("#161a21"));
        bar.setPadding(24, 16, 24, 16);

        badge = new TextView(this);
        badge.setTextSize(12);
        badge.setTextColor(Color.parseColor("#8a93a5"));
        badge.setPadding(0, 0, 24, 0);
        bar.addView(badge, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        connBadge = new TextView(this);
        connBadge.setTextSize(12);
        connBadge.setPadding(0, 0, 20, 0);
        bar.addView(connBadge, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        Button fix = new Button(this);
        fix.setText("开启界面操作");
        fix.setTextSize(11);
        fix.setAllCaps(false);
        fix.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                openAccessibilitySettings();
            }
        });
        bar.addView(fix, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        root.addView(bar);

        status = new TextView(this);
        status.setText("正在连接小伴…");
        status.setTextColor(Color.parseColor("#8a93a5"));
        status.setTextSize(15);
        status.setPadding(48, 60, 48, 24);
        root.addView(status, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#0f1115"));
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        // 页面里的 fetch 失败时，让 JS 通知原生层重新探测地址
        web.addJavascriptInterface(new Object() {
            @android.webkit.JavascriptInterface
            public void onFetchFail() {
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        setConnBadge(false);
                        startProbe();
                    }
                });
            }
        }, "XiaobanNative");

        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                status.setVisibility(View.GONE);
            }

            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                if (failingUrl != null && failingUrl.equals(view.getUrl())) {
                    status.setVisibility(View.VISIBLE);
                    status.setText("连接断了，正在切换地址…");
                    startProbe();
                }
            }
        });
        root.addView(web, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        setContentView(root);

        // 启动本地能力服务（让 PC 能调手机）
        String err = LocalServer.start(this, TOKEN);
        Keeper.start(this);
        DisplayClient.init(this);
        if (err != null) {
            Toast.makeText(this, err, Toast.LENGTH_LONG).show();
        }

        String last = prefs().getString(KEY_LAST, "");
        if (last != null && last.length() > 0) {
            loadBase(last);
        }
        startProbe();
        refreshBadge();
        checkUpdate();

        // 向 PC 注册成终端 + 定时心跳（后台看板才看得到手机在线）
        ShellRunner.requestPermission();
        startHeartbeat();

        agent = new AgentLoop(this);
    }

    @Override
    protected void onResume() {
        super.onResume();
        refreshBadge();
        // 回到前台时重探一次（USB 拔插 / WiFi 切换后地址可能变了）
        startProbe();
    }

    /** 顶部状态：无障碍开没开、本地服务跑没跑 */
    private void refreshBadge() {
        boolean acc = XiaobanAccessibilityService.isReady();
        boolean srv = LocalServer.isRunning();
        String accText = acc ? "界面操作 ✓" : "界面操作 ✗";
        String srvText = srv ? (":" + LocalServer.PORT + " ✓") : (":" + LocalServer.PORT + " ✗");
        badge.setText(accText + "   " + srvText + "   v" + LocalServer.BuildConfigLike.VERSION_NAME);
        badge.setTextColor(acc ? Color.parseColor("#4ec9b0") : Color.parseColor("#e0a355"));
    }

    private void openAccessibilitySettings() {
        try {
            Intent i = new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS);
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(i);
            Toast.makeText(this, "找到「小伴 · 界面操作」并打开", Toast.LENGTH_LONG).show();
        } catch (Exception e) {
            Toast.makeText(this, "打不开设置页：" + e, Toast.LENGTH_LONG).show();
        }
    }

    private SharedPreferences prefs() {
        return getSharedPreferences(PREF, MODE_PRIVATE);
    }

    // ---------------------------------------------------------------- 地址探测

    private void startProbe() {
        final java.util.concurrent.atomic.AtomicReference<String> winner =
                new java.util.concurrent.atomic.AtomicReference<String>(null);
        final java.util.concurrent.CountDownLatch done =
                new java.util.concurrent.CountDownLatch(1);

        for (int i = 0; i < CANDIDATES.length; i++) {
            final String base = CANDIDATES[i];
            Thread t = new Thread(new Runnable() {
                @Override
                public void run() {
                    if (winner.get() != null) return;
                    if (probe(base)) {
                        if (winner.compareAndSet(null, base)) done.countDown();
                    }
                }
            }, "probe-" + i);
            t.setDaemon(true);
            t.start();
        }

        Thread waiter = new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    done.await(6, java.util.concurrent.TimeUnit.SECONDS);
                } catch (InterruptedException ignored) {
                }
                final String target = winner.get();
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        if (destroyed) return;
                        if (target != null) {
                            setConnBadge(true);
                            prefs().edit().putString(KEY_LAST, target).apply();
                            prefs().edit().putString("pc_base", target).putString("pc_token", TOKEN).apply();
                            if (!target.equals(curBase)) {
                                loadBase(target);
                            }
                            fetchBrainConfig(target);
                        } else {
                            // 连不上 PC：不换界面，只把角标变红，然后自动重连
                            setConnBadge(false);
                            status.setVisibility(View.GONE);
                            scheduleReconnect();
                        }
                    }
                });
            }
        }, "waiter");
        waiter.setDaemon(true);
        waiter.start();
    }

    private boolean probe(String base) {
        HttpURLConnection c = null;
        try {
            URL u = new URL(base + "/api/health");
            c = (HttpURLConnection) u.openConnection();
            c.setConnectTimeout(PROBE_TIMEOUT_MS);
            c.setReadTimeout(PROBE_TIMEOUT_MS);
            c.setRequestMethod("GET");
            c.setRequestProperty("X-PC-Token", TOKEN);
            return c.getResponseCode() == 200;
        } catch (Exception e) {
            return false;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private void loadBase(String base) {
        curBase = base;
        status.setVisibility(View.VISIBLE);
        status.setText("正在打开 " + base.replace("http://", "") + " …");
        web.loadUrl(base + "/?t=" + TOKEN);
    }

    // ---------------------------------------------------------------- 心跳

    private Thread heartbeatThread;

    private void startHeartbeat() {
        if (heartbeatThread != null) return;
        heartbeatThread = new Thread(new Runnable() {
            @Override
            public void run() {
                boolean registered = false;
                while (!destroyed) {
                    try {
                        String base = curBase;
                        if (base == null || base.length() == 0) {
                            base = prefs().getString(KEY_LAST, "");
                        }
                        if (base != null && base.length() > 0) {
                            if (!registered) {
                                JSONObject reg = new JSONObject();
                                reg.put("id", "phone");
                                reg.put("name", android.os.Build.MODEL);
                                reg.put("kind", "phone");
                                JSONObject meta = new JSONObject();
                                meta.put("app", "xiaoban");
                                meta.put("version", LocalServer.BuildConfigLike.VERSION_NAME);
                                meta.put("accessibility", XiaobanAccessibilityService.isReady());
                                meta.put("shell", ShellRunner.level());
                                reg.put("meta", meta);
                                postJson(base + "/api/sync/register", reg.toString());
                                registered = true;
                            }
                            JSONObject hb = new JSONObject();
                            hb.put("id", "phone");
                            postJson(base + "/api/sync/heartbeat", hb.toString());
                        }
                    } catch (Exception ignored) {
                    }
                    try {
                        Thread.sleep(45000);
                    } catch (InterruptedException e) {
                        break;
                    }
                }
            }
        }, "heartbeat");
        heartbeatThread.setDaemon(true);
        heartbeatThread.start();
    }

    private void postJson(String url, String body) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setRequestMethod("POST");
            c.setConnectTimeout(4000);
            c.setReadTimeout(6000);
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json");
            c.setRequestProperty("X-PC-Token", TOKEN);
            byte[] data = body.getBytes("UTF-8");
            c.setFixedLengthStreamingMode(data.length);
            c.getOutputStream().write(data);
            c.getResponseCode();
        } catch (Exception ignored) {
        } finally {
            if (c != null) c.disconnect();
        }
    }

    // ---------------------------------------------------------------- 连接状态 / 自动重连

    /** 右上角显示「已连/断开」。不换界面，只改角标。 */
    private void setConnBadge(boolean connected) {
        if (connBadge == null) return;
        connBadge.setText(connected ? "● 已连" : "● 断开");
        connBadge.setTextColor(Color.parseColor(connected ? "#4ec9b0" : "#e05555"));
    }

    /** 断了就每 15 秒自动重探，连上就恢复。 */
    private void scheduleReconnect() {
        if (destroyed) return;
        ui.postDelayed(new Runnable() {
            @Override
            public void run() {
                if (destroyed) return;
                startProbe();
            }
        }, 15000);
    }

    // ---------------------------------------------------------------- 离线自主模式（C 方案，已停用）

    /** 从 PC 同步模型配置，缓存下来，PC 离线时也能用。 */
    private void fetchBrainConfig(final String base) {
        new Thread(new Runnable() {
            @Override
            public void run() {
                JSONObject cfg = getJson(base + "/api/app/brain");
                if (cfg == null || !cfg.optBoolean("ok")) return;
                if (!cfg.optBoolean("usable")) return;   // 本机网关手机直连不了，跳过
                agent.saveBrainConfig(
                        cfg.optString("baseUrl", ""),
                        cfg.optString("apiKey", ""),
                        cfg.optString("model", ""));
                // 顺便同步记忆库（离线时当上下文用）
                agent.syncMemory(base, TOKEN);
            }
        }, "braincfg").start();
    }

    /** PC 连不上：切到手机原生聊天，用本地缓存的模型配置自己干活。 */
    private void showOfflineChat() {
        if (offlineView != null) {
            root.removeAllViews();
            root.addView(offlineView, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
            return;
        }

        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackgroundColor(Color.parseColor("#0f1115"));

        TextView hint = new TextView(this);
        hint.setText("电脑连不上，我先自己干着。");
        hint.setTextColor(Color.parseColor("#e0a355"));
        hint.setTextSize(13);
        hint.setPadding(32, 20, 32, 12);
        box.addView(hint);

        final android.widget.ScrollView scroll = new android.widget.ScrollView(this);
        scroll.setFocusable(false);
        scroll.setFocusableInTouchMode(false);
        final LinearLayout logBox = new LinearLayout(this);
        logBox.setOrientation(LinearLayout.VERTICAL);
        logBox.setPadding(24, 8, 24, 8);
        scroll.addView(logBox);
        box.addView(scroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setPadding(20, 12, 20, 20);
        row.setGravity(Gravity.BOTTOM);

        final android.widget.EditText input = new android.widget.EditText(this);
        input.setHint("说点什么…");
        input.setTextColor(Color.parseColor("#e6e9ef"));
        input.setHintTextColor(Color.parseColor("#6b7280"));
        input.setBackgroundColor(Color.parseColor("#161a21"));
        input.setPadding(24, 20, 24, 20);
        input.setTextSize(16);
        // 触摸模式下必须显式打开，否则点上去拿不到焦点（实测踩过）
        input.setFocusable(true);
        input.setFocusableInTouchMode(true);
        input.setClickable(true);
        input.setCursorVisible(true);
        row.addView(input, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        Button send = new Button(this);
        send.setText("发送");
        send.setAllCaps(false);
        row.addView(send);
        box.addView(row);

        offlineView = box;
        offlineLog = logBox;
        offlineInput = input;

        root.removeAllViews();
        root.addView(box, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        View.OnClickListener doSend = new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                String text = input.getText().toString().trim();
                if (text.length() == 0) return;
                input.setText("");
                addOfflineBubble("你：" + text, "#4ec9b0");
                agent.run(text, new AgentLoop.Callback() {
                    @Override
                    public void onSay(final String t) {
                        ui.post(new Runnable() {
                            @Override
                            public void run() { addOfflineBubble("小伴：" + t, "#e6e9ef"); }
                        });
                    }

                    @Override
                    public void onStep(final String note) {
                        ui.post(new Runnable() {
                            @Override
                            public void run() { addOfflineBubble("· " + note, "#6b7280"); }
                        });
                    }

                    @Override
                    public void onError(final String message) {
                        ui.post(new Runnable() {
                            @Override
                            public void run() { addOfflineBubble("!" + message, "#e05555"); }
                        });
                    }
                });
            }
        };
        send.setOnClickListener(doSend);
    }

    private void addOfflineBubble(String text, String color) {
        if (offlineLog == null) return;
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextColor(Color.parseColor(color));
        t.setTextSize(15);
        t.setPadding(8, 10, 8, 10);
        offlineLog.addView(t);
        if (offlineLog.getParent() instanceof android.widget.ScrollView) {
            final android.widget.ScrollView sv = (android.widget.ScrollView) offlineLog.getParent();
            sv.post(new Runnable() {
                @Override
                public void run() { sv.fullScroll(View.FOCUS_DOWN); }
            });
        }
    }

    // ---------------------------------------------------------------- 自更新

    /** 问 PC 要最新版本号，比当前新就下载安装。 */
    private void checkUpdate() {
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    String base = curBase;
                    if (base == null || base.length() == 0) {
                        base = prefs().getString(KEY_LAST, "");
                    }
                    if (base == null || base.length() == 0) return;

                    JSONObject v = getJson(base + "/api/app/version");
                    if (v == null || !v.optBoolean("ok")) return;
                    int remoteCode = v.optInt("versionCode", 0);
                    int localCode = getPackageManager().getPackageInfo(getPackageName(), 0).versionCode;
                    if (remoteCode <= localCode) return;

                    final String apkUrl = base + "/api/app/download";
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            Toast.makeText(MainActivity.this, "发现新版本，正在下载…", Toast.LENGTH_SHORT).show();
                        }
                    });
                    File apk = download(apkUrl);
                    if (apk != null) installApk(apk);
                } catch (Exception ignored) {
                }
            }
        }, "update").start();
    }

    private JSONObject getJson(String url) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setConnectTimeout(4000);
            c.setReadTimeout(8000);
            c.setRequestProperty("X-PC-Token", TOKEN);
            if (c.getResponseCode() != 200) return null;
            InputStream in = c.getInputStream();
            java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
            in.close();
            return new JSONObject(bos.toString("UTF-8"));
        } catch (Exception e) {
            return null;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private File download(String url) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setConnectTimeout(8000);
            c.setReadTimeout(60000);
            c.setRequestProperty("X-PC-Token", TOKEN);
            if (c.getResponseCode() != 200) return null;
            File out = ApkProvider.apkFile(this);
            FileOutputStream fos = new FileOutputStream(out);
            InputStream in = c.getInputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) fos.write(buf, 0, n);
            fos.close();
            in.close();
            return out;
        } catch (Exception e) {
            return null;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private void installApk(File apk) {
        try {
            if (Build.VERSION.SDK_INT >= 26 && !getPackageManager().canRequestPackageInstalls()) {
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        Toast.makeText(MainActivity.this, "请先允许「安装未知应用」", Toast.LENGTH_LONG).show();
                        try {
                            Intent i = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                    Uri.parse("package:" + getPackageName()));
                            startActivity(i);
                        } catch (Exception ignored) {
                        }
                    }
                });
                return;
            }
            Uri uri = ApkProvider.apkUri();
            Intent i = new Intent(Intent.ACTION_VIEW);
            i.setDataAndType(uri, "application/vnd.android.package-archive");
            i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(i);
        } catch (Exception e) {
            Toast.makeText(this, "拉起安装失败：" + e, Toast.LENGTH_LONG).show();
        }
    }

    // ---------------------------------------------------------------- 生命周期

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK && web != null && web.canGoBack()) {
            web.goBack();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    protected void onDestroy() {
        destroyed = true;
        if (web != null) {
            root.removeView(web);
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}

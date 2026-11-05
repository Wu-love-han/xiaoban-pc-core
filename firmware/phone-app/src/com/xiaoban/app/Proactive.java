package com.xiaoban.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * 主动行为：不等人说话，自己判断该不该开口。
 *
 * 为什么需要这个类：
 *   光在提示词里写「你可以主动发消息」，AI 做不到——因为 AgentLoop 只在
 *   用户发消息时才跑。要真主动，必须有一个后台循环，定时叫醒它。
 *
 * 机制：
 *   每 CHECK_INTERVAL_MS 醒一次，检查三件事：
 *     1. 有没有别的 AI 发来的未读消息 → 有就回
 *     2. 隔了太久没联系 → 可以问一句
 *     3. 有没有到点的提醒 → 提醒
 *   然后让模型决定「现在要不要说话、说什么」。
 *   模型可以选择 SKIP（不说），避免刷屏。
 *
 * 限流：
 *   - 最短间隔 MIN_GAP_MS（30 分钟），防止烦人
 *   - 用户说「别吵」就暂停（settings 里存）
 */
public final class Proactive {
    private static final String TAG = "XiaobanProactive";

    /** 多久检查一次（10 分钟）。 */
    private static final long CHECK_INTERVAL_MS = 10 * 60 * 1000L;
    /** 两次主动说话之间至少隔多久（30 分钟）。 */
    private static final long MIN_GAP_MS = 30 * 60 * 1000L;

    private static volatile boolean started = false;
    private static volatile boolean enabled = true;
    private static Thread worker;
    private static SharedPreferences sp;

    private Proactive() {}

    public static void start(Context ctx) {
        if (started) return;
        started = true;
        sp = ctx.getApplicationContext().getSharedPreferences("xiaoban", Context.MODE_PRIVATE);
        enabled = sp.getBoolean("proactive_enabled", true);
        worker = new Thread(new Runnable() {
            @Override
            public void run() {
                loop();
            }
        }, "xiaoban-proactive");
        worker.setDaemon(true);
        worker.start();
        Log.i(TAG, "主动行为线程已启动，检查间隔 " + (CHECK_INTERVAL_MS / 60000) + " 分钟");
    }

    public static void setEnabled(boolean on) {
        enabled = on;
        if (sp != null) sp.edit().putBoolean("proactive_enabled", on).apply();
        Log.i(TAG, "主动行为: " + (on ? "开" : "关"));
    }

    public static boolean isEnabled() {
        return enabled;
    }

    private static void loop() {
        // 启动后先等 2 分钟，别一上来就说话
        try {
            Thread.sleep(2 * 60 * 1000L);
        } catch (InterruptedException e) {
            return;
        }
        while (true) {
            try {
                if (enabled) tick();
                Thread.sleep(CHECK_INTERVAL_MS);
            } catch (InterruptedException e) {
                return;
            } catch (Throwable e) {
                Log.w(TAG, "tick: " + e);
                try {
                    Thread.sleep(CHECK_INTERVAL_MS);
                } catch (InterruptedException ie) {
                    return;
                }
            }
        }
    }

    private static void tick() {
        if (sp == null) return;

        // 限流：距上次主动说话不够 30 分钟就跳过
        long last = sp.getLong("last_proactive_ms", 0);
        if (System.currentTimeMillis() - last < MIN_GAP_MS) return;

        String base = sp.getString("pc_base", "");
        String token = sp.getString("token", "");
        if (base.length() == 0) return;

        // 1) 先看有没有别的 AI 发来的消息
        String inbox = httpGet(base + "/api/agents/inbox?agent_id=phone&limit=5&unread_only=true", token);
        boolean hasInbox = inbox != null && inbox.contains("\"count\"") && !inbox.contains("\"count\":0");

        // 2) 看上次聊天多久以前
        long lastChat = sp.getLong("last_chat_ms", 0);
        long sinceChat = System.currentTimeMillis() - lastChat;
        boolean longSilence = sinceChat > 6 * 60 * 60 * 1000L;   // 超过 6 小时

        if (!hasInbox && !longSilence) return;

        // 3) 让模型决定
        String decision = askModel(base, token, hasInbox ? inbox : "", longSilence, sinceChat);
        if (decision == null) return;

        String text = decision.trim();
        if (text.length() == 0 || text.contains("SKIP")) {
            Log.i(TAG, "模型决定不说话");
            return;
        }

        // 4) 推给 WH
        if (pushMessage(base, token, text)) {
            sp.edit().putLong("last_proactive_ms", System.currentTimeMillis()).apply();
            Log.i(TAG, "主动说了：" + text.substring(0, Math.min(40, text.length())));
        }
    }

    /** 问模型：现在该不该说话、说什么。 */
    private static String askModel(String base, String token, String inboxJson,
                                   boolean longSilence, long sinceChat) {
        try {
            String apiKey = sp.getString("api_key", "");
            String apiBase = sp.getString("api_base", "https://api.deepseek.com/v1");
            String model = sp.getString("model", "deepseek-chat");
            if (apiKey.length() == 0) return null;

            String now = new java.text.SimpleDateFormat("yyyy-MM-dd HH:mm EEEE",
                    java.util.Locale.CHINA).format(new java.util.Date());

            String sys = "你是小随，WH 的手机端 AI 伙伴。现在你没人说话，自己判断要不要主动开口。\n"
                    + "判断标准：\n"
                    + "- 有别的 AI 找你 → 必须回\n"
                    + "- 隔了很久没联系 + 有值得说的 → 可以说一句\n"
                    + "- 没什么事 → 回 SKIP，别硬找话说\n"
                    + "要说话就直接输出那句话（口语、短句、不超过 50 字，别用「您好」这种客套）。\n"
                    + "不要说话就只输出四个字母：SKIP";

            String user = "现在：" + now + "\n"
                    + (inboxJson.length() > 0 ? "别的 AI 发来的消息：" + inboxJson + "\n" : "")
                    + (longSilence ? "距上次聊天已经 " + (sinceChat / 3600000) + " 小时了\n" : "");

            JSONArray msgs = new JSONArray();
            msgs.put(new JSONObject().put("role", "system").put("content", sys));
            msgs.put(new JSONObject().put("role", "user").put("content", user));

            JSONObject body = new JSONObject();
            body.put("model", model);
            body.put("messages", msgs);
            body.put("max_tokens", 120);
            body.put("temperature", 0.8);

            String resp = postJson(apiBase + "/chat/completions", body.toString(), apiKey);
            if (resp == null) return null;
            JSONObject d = new JSONObject(resp);
            JSONArray choices = d.optJSONArray("choices");
            if (choices == null || choices.length() == 0) return null;
            return choices.getJSONObject(0).getJSONObject("message").optString("content", "");
        } catch (Throwable e) {
            Log.w(TAG, "askModel: " + e);
            return null;
        }
    }

    private static boolean pushMessage(String base, String token, String text) {
        try {
            JSONObject o = new JSONObject();
            o.put("text", text);
            o.put("kind", "notice");
            o.put("source", "phone");
            o.put("priority", 1);
            return postJson(base + "/api/proactive/push", o.toString(), token) != null;
        } catch (Throwable e) {
            return false;
        }
    }

    private static String httpGet(String url, String token) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setRequestMethod("GET");
            c.setConnectTimeout(6000);
            c.setReadTimeout(10000);
            if (token != null && token.length() > 0) c.setRequestProperty("X-PC-Token", token);
            if (c.getResponseCode() < 200 || c.getResponseCode() >= 300) return null;
            return readAll(c.getInputStream());
        } catch (Throwable e) {
            return null;
        } finally {
            if (c != null) try { c.disconnect(); } catch (Throwable ignored) {}
        }
    }

    private static String postJson(String url, String body, String token) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setRequestMethod("POST");
            c.setDoOutput(true);
            c.setConnectTimeout(8000);
            c.setReadTimeout(30000);
            c.setRequestProperty("Content-Type", "application/json");
            if (token != null && token.length() > 0) {
                c.setRequestProperty("X-PC-Token", token);
                c.setRequestProperty("Authorization", "Bearer " + token);
            }
            OutputStream os = c.getOutputStream();
            os.write(body.getBytes("UTF-8"));
            os.close();
            if (c.getResponseCode() < 200 || c.getResponseCode() >= 300) return null;
            return readAll(c.getInputStream());
        } catch (Throwable e) {
            return null;
        } finally {
            if (c != null) try { c.disconnect(); } catch (Throwable ignored) {}
        }
    }

    private static String readAll(InputStream is) throws Exception {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int n;
        while ((n = is.read(buf)) > 0) bos.write(buf, 0, n);
        is.close();
        return new String(bos.toByteArray(), "UTF-8");
    }
}

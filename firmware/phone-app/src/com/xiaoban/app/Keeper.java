package com.xiaoban.app;

import android.content.Context;
import android.provider.Settings;
import android.util.Log;

/**
 * 特权通道保活 + 无障碍自动恢复。
 *
 * 思路来自 ccch1mneyyy/dsh-Go 的 privileged-keep 设计（AGPL 项目，这里只学思路不抄代码）：
 *   - 事件驱动，不做高频轮询
 *   - 只在「手机操控开关开着 + 有权限」时才尝试恢复
 *   - 只改自己那条无障碍服务项，不动别人的
 *   - 失败后延长重试间隔，避免死循环
 *
 * 解决的实际问题：
 *   App 重装/被系统杀之后无障碍必掉，用户得手动去系统设置点一遍。
 *   有了这个，只要 Shizuku 还在，就能自己修回来。
 */
public final class Keeper {
    private static final String TAG = "XiaobanKeeper";

    /** 自己那条无障碍服务。 */
    public static final String MY_SERVICE =
            "com.xiaoban.app/com.xiaoban.app.XiaobanAccessibilityService";

    /** 重试间隔：基础 30 秒，连续失败翻倍，最长 10 分钟。 */
    private static final long BASE_INTERVAL_MS = 30_000L;
    private static final long MAX_INTERVAL_MS = 600_000L;

    private static volatile boolean started = false;
    private static volatile boolean enabled = true;   // 用户开关（暂时默认开）
    private static volatile Thread worker;
    private static volatile long interval = BASE_INTERVAL_MS;

    private Keeper() {}

    public static void start(final Context ctx) {
        if (started) return;
        started = true;
        final Context app = ctx.getApplicationContext();
        worker = new Thread(new Runnable() {
            @Override
            public void run() {
                loop(app);
            }
        }, "xiaoban-keeper");
        worker.setDaemon(true);
        worker.start();
        Log.i(TAG, "保活线程已启动，间隔 " + (BASE_INTERVAL_MS / 1000) + " 秒");
    }

    public static void setEnabled(boolean on) {
        enabled = on;
        if (on) interval = BASE_INTERVAL_MS;
        Log.i(TAG, "保活开关: " + (on ? "开" : "关"));
    }

    public static boolean isEnabled() {
        return enabled;
    }

    private static void loop(Context ctx) {
        while (true) {
            try {
                Thread.sleep(interval);
            } catch (InterruptedException e) {
                return;
            }
            if (!enabled) continue;

            boolean didSomething = tick(ctx);
            // 成功就回到基础间隔，失败就翻倍（最多 10 分钟）
            if (didSomething) {
                interval = BASE_INTERVAL_MS;
            } else {
                interval = Math.min(interval * 2, MAX_INTERVAL_MS);
            }
        }
    }

    /** 返回 true 表示这次有实际动作（说明通道是好的）。 */
    private static boolean tick(Context ctx) {
        boolean shizukuOk = ShellRunner.shizukuAlive() && ShellRunner.shizukuGranted();
        boolean a11yOk = a11yEnabled(ctx);

        if (a11yOk) return true;   // 都好，什么都不做

        if (!shizukuOk) {
            Log.w(TAG, "无障碍没开，但 Shizuku 也不可用，修不了");
            return false;
        }

        // 无障碍掉了但 Shizuku 在 → 自己修回来
        Log.i(TAG, "检测到无障碍没开，尝试自动恢复");
        boolean ok = restoreA11y();
        Log.i(TAG, ok ? "无障碍已恢复" : "无障碍恢复失败");
        return ok;
    }

    /** 无障碍服务当前开着吗。 */
    public static boolean a11yEnabled(Context ctx) {
        try {
            String cur = Settings.Secure.getString(
                    ctx.getContentResolver(), "enabled_accessibility_services");
            int on = Settings.Secure.getInt(
                    ctx.getContentResolver(), "accessibility_enabled", 0);
            return on == 1 && cur != null && cur.contains(MY_SERVICE);
        } catch (Throwable e) {
            return false;
        }
    }

    /**
     * 用 Shizuku 的 shell 把无障碍开回来。
     * 只动自己那条，别人的服务项保留。
     */
    public static boolean restoreA11y() {
        try {
            // 先读现有的，保留别人
            String cur = ShellRunner.exec("settings get secure enabled_accessibility_services", 8000);
            String list = "";
            for (String line : cur.split("\n")) {
                line = line.trim();
                if (line.startsWith("com.") || line.startsWith("moe.")) {
                    list = line;
                    break;
                }
            }
            if (list.equals("null")) list = "";
            StringBuilder sb = new StringBuilder(list);
            if (sb.indexOf(MY_SERVICE) < 0) {
                if (sb.length() > 0) sb.append(":");
                sb.append(MY_SERVICE);
            }
            String cmd = "settings put secure enabled_accessibility_services '"
                    + sb + "'; settings put secure accessibility_enabled 1; echo KEEPER_OK";
            String out = ShellRunner.exec(cmd, 12000);
            return out != null && out.indexOf("KEEPER_OK") >= 0;
        } catch (Throwable e) {
            Log.w(TAG, "restoreA11y: " + e);
            return false;
        }
    }
}

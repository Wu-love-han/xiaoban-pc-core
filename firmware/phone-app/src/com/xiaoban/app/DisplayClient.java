package com.xiaoban.app;

import android.content.ComponentName;
import android.content.Context;
import android.content.ServiceConnection;
import android.os.IBinder;
import android.util.Log;

import rikka.shizuku.Shizuku;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * 虚拟屏客户端：把 XiaobanDisplayService 绑到 Shizuku 的 UserService 上。
 *
 * 绑上去之后，服务里的代码以 shell 身份跑，才有权限建虚拟屏、注入事件。
 */
public final class DisplayClient {
    private static final String TAG = "XiaobanDisplay";
    private static final String TAG_NAME = "xiaoban.vdisplay";

    private static IXiaobanDisplay remote;
    private static boolean binding = false;
    private static Context appCtx;

    private DisplayClient() {}

    public static void init(Context ctx) {
        appCtx = ctx.getApplicationContext();
    }

    /** 拿到服务；没绑过就先绑（最多等 15 秒）。 */
    public static synchronized IXiaobanDisplay get() {
        if (remote != null) {
            try {
                remote.displayId();
                return remote;      // 还活着
            } catch (Throwable e) {
                remote = null;      // 掉了，重绑
            }
        }
        if (binding || appCtx == null) return null;
        if (!ShellRunner.shizukuAlive() || !ShellRunner.shizukuGranted()) {
            Log.w(TAG, "Shizuku 不可用，绑不了虚拟屏服务");
            return null;
        }

        binding = true;
        final CountDownLatch latch = new CountDownLatch(1);
        final IXiaobanDisplay[] holder = new IXiaobanDisplay[1];

        try {
            Shizuku.UserServiceArgs args = new Shizuku.UserServiceArgs(
                    new ComponentName(appCtx, XiaobanDisplayService.class))
                    .tag(TAG_NAME)
                    .processNameSuffix("vdisplay")
                    .version(1)
                    .daemon(false);

            ServiceConnection conn = new ServiceConnection() {
                @Override
                public void onServiceConnected(ComponentName name, IBinder binder) {
                    holder[0] = IXiaobanDisplay.Stub.asInterface(binder);
                    latch.countDown();
                }

                @Override
                public void onServiceDisconnected(ComponentName name) {
                    Log.w(TAG, "虚拟屏服务断开");
                    remote = null;
                }
            };

            Shizuku.bindUserService(args, conn);
            if (latch.await(35, TimeUnit.SECONDS) && holder[0] != null) {
                remote = holder[0];
                Log.i(TAG, "虚拟屏服务已绑定");
                return remote;
            }
            Log.w(TAG, "绑定超时");
            return null;
        } catch (Throwable e) {
            Log.w(TAG, "绑定失败: " + e);
            return null;
        } finally {
            binding = false;
        }
    }

    public static synchronized void reset() {
        remote = null;
    }
}

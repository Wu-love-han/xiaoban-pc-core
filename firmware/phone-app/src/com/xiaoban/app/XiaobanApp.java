package com.xiaoban.app;

import android.app.Application;
import android.util.Log;

/**
 * Application 入口。
 *
 * 唯一的作用：开启 Shizuku 的多进程支持。
 *
 * 为什么必须：虚拟屏服务跑在独立进程（Shizuku 的 UserService），
 * 那个进程要访问 ShizukuProvider 才能拿到 binder。
 * 不调 enableMultiProcessSupport 的话，UserService 进程里会报
 * "provider is null moe.shizuku.privileged.api.shizuku"，服务永远绑不上。
 */
public class XiaobanApp extends Application {
    @Override
    public void onCreate() {
        super.onCreate();
        try {
            // 参数是「最大进程 id」。我们有主进程(0) + vdisplay 进程(1) + apk provider，给 8 够用
            rikka.shizuku.ShizukuProvider.enableMultiProcessSupport(true);
            Log.i("XiaobanApp", "Shizuku 多进程支持已开启");
        } catch (Throwable e) {
            Log.w("XiaobanApp", "开启多进程支持失败: " + e);
        }
    }
}

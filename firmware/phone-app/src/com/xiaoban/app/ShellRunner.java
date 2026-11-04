package com.xiaoban.app;

import android.content.pm.PackageManager;
import android.util.Log;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;

import rikka.shizuku.Shizuku;

/**
 * 小伴 · 系统命令执行器
 *
 * 优先走 Shizuku（借 ADB shell 权限，无需 root）：
 *   - 能装/卸应用、改系统设置、读 /data 下可读文件、模拟输入等
 * 拿不到 Shizuku 就退回 App 自己的 shell（权限跟 App 一样，很有限）。
 */
public class ShellRunner {

    private static final String TAG = "XiaobanShell";
    public static final int REQUEST_CODE = 4213;

    /** Shizuku 服务在不在（装了并且服务跑起来了）。 */
    public static boolean shizukuAlive() {
        try {
            return Shizuku.pingBinder();
        } catch (Throwable e) {
            return false;
        }
    }

    /** 有没有拿到 Shizuku 授权。 */
    public static boolean shizukuGranted() {
        try {
            if (!Shizuku.pingBinder()) return false;
            return Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED;
        } catch (Throwable e) {
            return false;
        }
    }

    /** 申请授权（Shizuku 会弹窗，用户点允许）。 */
    public static void requestPermission() {
        try {
            if (Shizuku.pingBinder() && !shizukuGranted()) {
                Shizuku.requestPermission(REQUEST_CODE);
            }
        } catch (Throwable e) {
            Log.w(TAG, "requestPermission: " + e);
        }
    }

    /** 当前能力级别：shizuku / app */
    public static String level() {
        if (shizukuGranted()) return "shizuku";
        if (shizukuAlive()) return "shizuku-unauthorized";
        return "app";
    }

    /**
     * 跑一条命令。返回 [退出码, 输出]。
     * level=shizuku 时是真 shell 权限，否则只有 App 自己的权限。
     */
    public static String exec(String cmd, int timeoutMs) {
        Process p = null;
        try {
            if (shizukuGranted()) {
                p = newProcessViaShizuku(new String[]{"sh", "-c", cmd});
            } else {
                p = Runtime.getRuntime().exec(new String[]{"sh", "-c", cmd});
            }
            if (p == null) return "拿不到进程（Shizuku 授权可能失效了）";
            final Process proc = p;

            // 超时保护
            final Thread killer = new Thread(new Runnable() {
                @Override
                public void run() {
                    try {
                        Thread.sleep(timeoutMs);
                        proc.destroy();
                    } catch (Exception ignored) {
                    }
                }
            });
            killer.setDaemon(true);
            killer.start();

            String out = readAll(p.getInputStream());
            String err = readAll(p.getErrorStream());
            int code = p.waitFor();
            killer.interrupt();

            StringBuilder sb = new StringBuilder();
            sb.append("退出码 ").append(code).append("\n");
            if (out.length() > 0) sb.append(out);
            if (err.length() > 0) sb.append("\n[stderr]\n").append(err);
            String s = sb.toString();
            return s.length() > 3000 ? s.substring(0, 3000) + "\n…（已截断）" : s;
        } catch (Throwable e) {
            return "执行失败：" + e;
        } finally {
            if (p != null) try { p.destroy(); } catch (Exception ignored) {}
        }
    }

    /** 通过 Shizuku 的 IShizukuService 起一个真 shell 进程（shell 权限）。 */
    private static Process newProcessViaShizuku(String[] cmd) {
        try {
            moe.shizuku.server.IShizukuService svc =
                    moe.shizuku.server.IShizukuService.Stub.asInterface(Shizuku.getBinder());
            if (svc == null) return null;
            moe.shizuku.server.IRemoteProcess rp = svc.newProcess(cmd, null, null);
            if (rp == null) return null;
            return new RemoteProcessWrapper(rp);
        } catch (Throwable e) {
            Log.w(TAG, "newProcessViaShizuku: " + e);
            return null;
        }
    }

    /** 把 IRemoteProcess 包成标准 Process，方便复用读流逻辑。 */
    private static final class RemoteProcessWrapper extends Process {
        private final moe.shizuku.server.IRemoteProcess rp;
        private java.io.OutputStream stdin;

        RemoteProcessWrapper(moe.shizuku.server.IRemoteProcess rp) {
            this.rp = rp;
        }

        @Override
        public java.io.OutputStream getOutputStream() {
            if (stdin == null) {
                try {
                    stdin = new android.os.ParcelFileDescriptor.AutoCloseOutputStream(rp.getOutputStream());
                } catch (Exception e) {
                    stdin = new java.io.ByteArrayOutputStream();
                }
            }
            return stdin;
        }

        @Override
        public java.io.InputStream getInputStream() {
            try {
                return new android.os.ParcelFileDescriptor.AutoCloseInputStream(rp.getInputStream());
            } catch (Exception e) {
                return new java.io.ByteArrayInputStream(new byte[0]);
            }
        }

        @Override
        public java.io.InputStream getErrorStream() {
            try {
                return new android.os.ParcelFileDescriptor.AutoCloseInputStream(rp.getErrorStream());
            } catch (Exception e) {
                return new java.io.ByteArrayInputStream(new byte[0]);
            }
        }

        @Override
        public int waitFor() throws InterruptedException {
            try {
                return rp.waitFor();
            } catch (Exception e) {
                return -1;
            }
        }

        @Override
        public int exitValue() {
            try {
                return rp.waitFor();
            } catch (Exception e) {
                return -1;
            }
        }

        @Override
        public void destroy() {
            try {
                rp.destroy();
            } catch (Exception ignored) {
            }
        }
    }

    private static String readAll(InputStream in) {
        try {
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
            in.close();
            return bos.toString("UTF-8");
        } catch (Exception e) {
            return "";
        }
    }
}

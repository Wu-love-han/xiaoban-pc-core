package com.xiaoban.app;

import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;

/**
 * 小伴 · 本地能力服务
 *
 * 把手机的无障碍能力暴露成 HTTP，让 PC 那边直接调：
 *   GET  /ping                    探活
 *   GET  /tree?limit=200          实时界面树（JSON）
 *   GET  /foreground              当前前台包名
 *   POST /click   {text} 或 {x,y}  点节点 / 点坐标
 *   POST /type    {text}          往输入框写文字
 *   POST /key     {name}          back/home/recents/notifications
 *
 * 鉴权：请求头 X-PC-Token 必须等于 PC 端同一个 token。
 * 监听 0.0.0.0，所以 Tailscale / 局域网都能连。
 */
public class LocalServer {

    private static final String TAG = "XiaobanServer";
    public static final int PORT = 9123;

    private static volatile boolean running = false;
    private static android.content.Context appCtx = null;
    private static ServerSocket serverSocket;
    private static Thread acceptThread;

    public static synchronized boolean isRunning() {
        return running;
    }

    public static synchronized String start(android.content.Context ctx, final String token) {
        appCtx = ctx == null ? null : ctx.getApplicationContext();
        if (running) return null;
        try {
            serverSocket = new ServerSocket(PORT);
            running = true;
        } catch (Exception e) {
            return "监听 " + PORT + " 失败：" + e;
        }
        acceptThread = new Thread(new Runnable() {
            @Override
            public void run() {
                while (running) {
                    try {
                        final Socket s = serverSocket.accept();
                        // 每个连接一个线程：无障碍操作可能阻塞（比如点了会启动新页面），
                        // 单线程处理会把整个服务堵死（实测踩过，点击超时 16 秒）
                        Thread t = new Thread(new Runnable() {
                            @Override
                            public void run() {
                                try {
                                    handle(s, token);
                                } finally {
                                    try { s.close(); } catch (Exception ignored) {}
                                }
                            }
                        }, "xiaoban-req");
                        t.setDaemon(true);
                        t.start();
                    } catch (Exception e) {
                        if (running) Log.w(TAG, "accept: " + e);
                    }
                }
            }
        }, "xiaoban-http");
        acceptThread.setDaemon(true);
        acceptThread.start();
        Log.i(TAG, "本地服务已启动 :" + PORT);
        return null;
    }

    public static synchronized void stop() {
        running = false;
        try { if (serverSocket != null) serverSocket.close(); } catch (Exception ignored) {}
        serverSocket = null;
    }

    // ---------------------------------------------------------------- 请求处理

    private static void handle(Socket socket, String token) {
        try {
            socket.setSoTimeout(20000);
            InputStream in = socket.getInputStream();

            // ---- 按「字节」读请求头，直到 \r\n\r\n ----
            ByteArrayOutputStream headBuf = new ByteArrayOutputStream();
            int b;
            int matched = 0;
            while ((b = in.read()) >= 0) {
                headBuf.write(b);
                if ((b == '\r' && (matched == 0 || matched == 2))
                        || (b == '\n' && (matched == 1 || matched == 3))) {
                    matched++;
                    if (matched == 4) break;
                } else {
                    matched = (b == '\r') ? 1 : 0;
                }
            }
            String head = new String(headBuf.toByteArray(), "UTF-8");
            String[] headLines = head.split("\r\n");
            if (headLines.length == 0) return;

            String[] parts = headLines[0].split(" ");
            if (parts.length < 2) return;
            String method = parts[0];
            String path = parts[1];

            int contentLength = 0;
            String givenToken = "";
            for (int i = 1; i < headLines.length; i++) {
                String line = headLines[i];
                int idx = line.indexOf(':');
                if (idx <= 0) continue;
                String k = line.substring(0, idx).trim().toLowerCase();
                String v = line.substring(idx + 1).trim();
                if (k.equals("content-length")) {
                    try { contentLength = Integer.parseInt(v); } catch (Exception ignored) {}
                } else if (k.equals("x-pc-token")) {
                    givenToken = v;
                }
            }

            // ---- 鉴权 ----
            if (token != null && token.length() > 0 && !token.equals(givenToken)) {
                respond(socket, 401, "{\"ok\":false,\"error\":\"token 不对\"}");
                return;
            }

            // ---- 按「字节」读请求体（Content-Length 是字节数，不是字符数！
            //      按字符读会导致中文请求体永远读不满 → 超时，实测踩过）----
            String body = "";
            if (contentLength > 0) {
                byte[] bodyBytes = new byte[contentLength];
                int read = 0;
                while (read < contentLength) {
                    int n = in.read(bodyBytes, read, contentLength - read);
                    if (n < 0) break;
                    read += n;
                }
                body = new String(bodyBytes, 0, read, "UTF-8");
            }

            String result = route(method, path, body);
            respond(socket, 200, result);
        } catch (Exception e) {
            Log.w(TAG, "handle: " + e);
            try {
                respond(socket, 500, "{\"ok\":false,\"error\":\"" + esc(e.toString()) + "\"}");
            } catch (Exception ignored) {}
        }
    }

    private static String route(String method, String fullPath, String body) {
        try {
            String path = fullPath;
            String query = "";
            int q = fullPath.indexOf('?');
            if (q >= 0) {
                path = fullPath.substring(0, q);
                query = fullPath.substring(q + 1);
            }

            XiaobanAccessibilityService svc = XiaobanAccessibilityService.get();

            if (path.equals("/ping")) {
                JSONObject o = new JSONObject();
                o.put("ok", true);
                o.put("app", "xiaoban");
                o.put("accessibility", XiaobanAccessibilityService.isReady());
                o.put("version", BuildConfigLike.VERSION_NAME);
                return o.toString();
            }

            // 需要无障碍的接口才检查（/shell、/open_app、/apps、/brain/info 不需要）
            boolean needAcc = path.equals("/tree") || path.equals("/click")
                    || path.equals("/type") || path.equals("/key") || path.equals("/foreground");
            if (needAcc && !XiaobanAccessibilityService.isReady()) {
                return "{\"ok\":false,\"error\":\"无障碍服务没开，请在系统设置里打开「小伴 · 界面操作」\"}";
            }

            if (path.equals("/tree")) {
                int limit = 200;
                for (String kv : query.split("&")) {
                    if (kv.startsWith("limit=")) {
                        try { limit = Integer.parseInt(kv.substring(6)); } catch (Exception ignored) {}
                    }
                }
                return svc.dumpTree(limit);
            }

            if (path.equals("/foreground")) {
                JSONObject o = new JSONObject();
                o.put("ok", true);
                o.put("package", svc.currentPackage());
                return o.toString();
            }

            if (path.equals("/click") && method.equals("POST")) {
                JSONObject req = new JSONObject(body == null || body.length() == 0 ? "{}" : body);
                String text = req.optString("text", "");
                String err;
                if (text.length() > 0) {
                    err = svc.clickByText(text);
                } else {
                    int x = req.optInt("x", -1);
                    int y = req.optInt("y", -1);
                    if (x < 0 || y < 0) return "{\"ok\":false,\"error\":\"要给 text 或 x,y\"}";
                    err = svc.clickXY(x, y) ? null : "手势点击失败";
                }
                JSONObject o = new JSONObject();
                o.put("ok", err == null);
                if (err != null) o.put("error", err);
                else o.put("done", true);
                return o.toString();
            }

            if (path.equals("/type") && method.equals("POST")) {
                JSONObject req = new JSONObject(body == null || body.length() == 0 ? "{}" : body);
                String text = req.optString("text", "");
                if (text.length() == 0) return "{\"ok\":false,\"error\":\"要给 text\"}";
                String err = svc.setText(text);
                JSONObject o = new JSONObject();
                o.put("ok", err == null);
                if (err != null) o.put("error", err);
                else o.put("count", text.length());
                return o.toString();
            }

            if (path.equals("/memory/info")) {
                android.content.SharedPreferences sp = appCtx == null
                        ? null
                        : appCtx.getSharedPreferences("xiaoban", android.content.Context.MODE_PRIVATE);
                if (sp == null) return "{\"ok\":false,\"error\":\"服务还没初始化\"}";
                JSONObject o = new JSONObject();
                o.put("ok", true);
                o.put("count", sp.getInt("mem_count", 0));
                o.put("version", sp.getInt("mem_version", 0));
                String block = sp.getString("mem_block", "");
                o.put("preview", block == null ? "" : block.substring(0, Math.min(300, block.length())));
                return o.toString();
            }

            if (path.equals("/brain/info")) {
                // 只报状态，不返回 key（防止被随便读走）
                android.content.SharedPreferences sp = appCtx == null
                        ? null
                        : appCtx.getSharedPreferences("xiaoban", android.content.Context.MODE_PRIVATE);
                if (sp == null) return "{\"ok\":false,\"error\":\"服务还没初始化\"}";
                String base = sp.getString("brain_base", "");
                JSONObject o = new JSONObject();
                o.put("ok", true);
                o.put("configured", base != null && base.length() > 0);
                o.put("baseUrl", base == null ? "" : base);
                o.put("model", sp.getString("brain_model", ""));
                o.put("hasKey", (sp.getString("brain_key", "")).length() > 0);
                return o.toString();
            }

            if (path.equals("/screenshot")) {
                // 用 Shizuku 的 shell 跑 screencap，再读回来转 base64（不依赖 USB）
                if (!"shizuku".equals(ShellRunner.level())) {
                    return "{\"ok\":false,\"error\":\"没有 shell 权限，截不了屏\"}";
                }
                String f = "/sdcard/.xb_shot.png";
                String out = ShellRunner.exec("screencap -p " + f + " && echo SHOT_OK", 20000);
                if (out.indexOf("SHOT_OK") < 0) {
                    return "{\"ok\":false,\"error\":\"截图失败：" + out.replace("\"", "'").substring(0, Math.min(120, out.length())) + "\"}";
                }
                java.io.File file = new java.io.File(f);
                if (!file.exists()) return "{\"ok\":false,\"error\":\"截图文件不存在\"}";
                byte[] data = new byte[(int) file.length()];
                java.io.FileInputStream fis = new java.io.FileInputStream(file);
                int read = 0;
                while (read < data.length) {
                    int n = fis.read(data, read, data.length - read);
                    if (n < 0) break;
                    read += n;
                }
                fis.close();
                file.delete();
                JSONObject o = new JSONObject();
                o.put("ok", true);
                o.put("size", read);
                o.put("base64", android.util.Base64.encodeToString(data, android.util.Base64.NO_WRAP));
                return o.toString();
            }

            if (path.equals("/open_app") && method.equals("POST")) {
                JSONObject req = new JSONObject(body == null || body.length() == 0 ? "{}" : body);
                String pkg = req.optString("package", "").trim();
                if (pkg.length() == 0) return "{\"ok\":false,\"error\":\"要给 package\"}";
                if (appCtx == null) return "{\"ok\":false,\"error\":\"服务还没初始化\"}";
                android.content.Intent it = appCtx.getPackageManager().getLaunchIntentForPackage(pkg);
                if (it == null) return "{\"ok\":false,\"error\":\"没装这个应用，或拿不到启动入口：" + pkg + "\"}";
                it.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK);
                appCtx.startActivity(it);
                JSONObject o = new JSONObject();
                o.put("ok", true);
                o.put("package", pkg);
                return o.toString();
            }

            if (path.equals("/apps")) {
                if (appCtx == null) return "{\"ok\":false,\"error\":\"服务还没初始化\"}";
                JSONArray arr = new JSONArray();
                java.util.List<android.content.pm.ApplicationInfo> list =
                        appCtx.getPackageManager().getInstalledApplications(0);
                for (android.content.pm.ApplicationInfo ai : list) {
                    android.content.Intent li = appCtx.getPackageManager().getLaunchIntentForPackage(ai.packageName);
                    if (li == null) continue;
                    JSONObject o = new JSONObject();
                    o.put("package", ai.packageName);
                    o.put("label", String.valueOf(appCtx.getPackageManager().getApplicationLabel(ai)));
                    arr.put(o);
                }
                JSONObject o = new JSONObject();
                o.put("ok", true);
                o.put("count", arr.length());
                o.put("apps", arr);
                return o.toString();
            }

            // ------------------------------------------------ 虚拟屏（后台操作）
            if (path.startsWith("/vdisplay")) {
                IXiaobanDisplay vd = DisplayClient.get();
                if (vd == null) {
                    return "{\"ok\":false,\"error\":\"虚拟屏服务没起来（要 Shizuku 授权）\"}";
                }
                JSONObject req = new JSONObject(body == null || body.length() == 0 ? "{}" : body);
                try {
                    if (path.equals("/vdisplay/info")) {
                        JSONObject o = new JSONObject(vd.info());
                        o.put("ok", true);
                        return o.toString();
                    }
                    if (path.equals("/vdisplay/create")) {
                        int w = req.optInt("width", 720);
                        int h = req.optInt("height", 1600);
                        int dpi = req.optInt("dpi", 320);
                        int id = vd.createDisplay(w, h, dpi);
                        JSONObject o = new JSONObject();
                        o.put("ok", id >= 0);
                        o.put("displayId", id);
                        if (id < 0) o.put("error", "创建失败（这个 ROM 可能不支持）");
                        return o.toString();
                    }
                    if (path.equals("/vdisplay/release")) {
                        vd.releaseDisplay();
                        JSONObject o = new JSONObject();
                        o.put("ok", true);
                        return o.toString();
                    }
                    if (path.equals("/vdisplay/launch")) {
                        String pkg = req.optString("package", "");
                        JSONObject o = new JSONObject();
                        o.put("ok", vd.launchApp(pkg, -1));
                        o.put("package", pkg);
                        return o.toString();
                    }
                    if (path.equals("/vdisplay/tap")) {
                        JSONObject o = new JSONObject();
                        o.put("ok", vd.tap(-1, req.optInt("x"), req.optInt("y")));
                        return o.toString();
                    }
                    if (path.equals("/vdisplay/swipe")) {
                        JSONObject o = new JSONObject();
                        o.put("ok", vd.swipe(-1, req.optInt("x1"), req.optInt("y1"),
                                req.optInt("x2"), req.optInt("y2"), req.optInt("ms", 300)));
                        return o.toString();
                    }
                    if (path.equals("/vdisplay/key")) {
                        JSONObject o = new JSONObject();
                        o.put("ok", vd.key(-1, req.optInt("keycode")));
                        return o.toString();
                    }
                    if (path.equals("/vdisplay/type")) {
                        JSONObject o = new JSONObject();
                        o.put("ok", vd.text(-1, req.optString("text", "")));
                        return o.toString();
                    }
                    if (path.equals("/vdisplay/screenshot")) {
                        byte[] png = vd.screenshot(-1);
                        JSONObject o = new JSONObject();
                        if (png == null || png.length == 0) {
                            o.put("ok", false);
                            o.put("error", "截不到图（虚拟屏没内容）");
                        } else {
                            o.put("ok", true);
                            o.put("size", png.length);
                            o.put("base64", android.util.Base64.encodeToString(png, android.util.Base64.NO_WRAP));
                        }
                        return o.toString();
                    }
                    return "{\"ok\":false,\"error\":\"未知的 vdisplay 接口\"}";
                } catch (Throwable e) {
                    return "{\"ok\":false,\"error\":\"" + String.valueOf(e).replace("\"", "'") + "\"}";
                }
            }

            if (path.equals("/shell/info")) {
                JSONObject o = new JSONObject();
                o.put("ok", true);
                o.put("level", ShellRunner.level());
                o.put("shizukuAlive", ShellRunner.shizukuAlive());
                o.put("shizukuGranted", ShellRunner.shizukuGranted());
                return o.toString();
            }

            if (path.equals("/shell") && method.equals("POST")) {
                JSONObject req = new JSONObject(body == null || body.length() == 0 ? "{}" : body);
                String cmd = req.optString("cmd", "");
                if (cmd.length() == 0) return "{\"ok\":false,\"error\":\"要给 cmd\"}";
                int timeout = req.optInt("timeout", 15000);
                if (timeout <= 0 || timeout > 60000) timeout = 15000;
                String out = ShellRunner.exec(cmd, timeout);
                JSONObject o = new JSONObject();
                o.put("ok", true);
                o.put("level", ShellRunner.level());
                o.put("output", out);
                return o.toString();
            }

            if (path.equals("/key") && method.equals("POST")) {
                JSONObject req = new JSONObject(body == null || body.length() == 0 ? "{}" : body);
                String name = req.optString("name", "");
                boolean ok = svc.globalAction(name);
                JSONObject o = new JSONObject();
                o.put("ok", ok);
                if (!ok) o.put("error", "认不出这个动作：" + name);
                return o.toString();
            }

            return "{\"ok\":false,\"error\":\"没有这个接口：" + esc(path) + "\"}";
        } catch (Exception e) {
            return "{\"ok\":false,\"error\":\"" + esc(e.toString()) + "\"}";
        }
    }

    private static void respond(Socket socket, int code, String json) {
        try {
            byte[] data = json.getBytes("UTF-8");
            ByteArrayOutputStream head = new ByteArrayOutputStream();
            String status = code == 200 ? "200 OK" : (code == 401 ? "401 Unauthorized" : "500 Internal Server Error");
            head.write(("HTTP/1.1 " + status + "\r\n").getBytes("UTF-8"));
            head.write("Content-Type: application/json; charset=utf-8\r\n".getBytes("UTF-8"));
            head.write(("Content-Length: " + data.length + "\r\n").getBytes("UTF-8"));
            head.write("Connection: close\r\n\r\n".getBytes("UTF-8"));
            OutputStream out = socket.getOutputStream();
            out.write(head.toByteArray());
            out.write(data);
            out.flush();
        } catch (Exception ignored) {}
    }

    private static String esc(String s) {
        return s == null ? "" : s.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    /** 版本号常量（避免依赖 BuildConfig） */
    public static final class BuildConfigLike {
        public static final String VERSION_NAME = "2.5.0";
    }
}

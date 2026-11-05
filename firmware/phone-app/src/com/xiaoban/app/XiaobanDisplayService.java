package com.xiaoban.app;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.PixelFormat;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.Image;
import android.media.ImageReader;
import android.os.SystemClock;
import android.view.Display;
import android.view.InputDevice;
import android.view.InputEvent;
import android.view.KeyCharacterMap;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.Surface;

import java.io.ByteArrayOutputStream;
import java.lang.reflect.Method;

/**
 * 虚拟屏服务：跑在 Shizuku 的 UserService 进程里（shell 身份 uid=2000）。
 *
 * 为什么必须跑在这里：
 *   - 创建虚拟屏要 CREATE_VIRTUAL_DISPLAY 权限（signature 级）
 *   - 注入事件要 INJECT_EVENTS 权限（signature 级）
 *   - shell 两个都有；普通 App 都没有
 *
 * 思路参考 HakaI963/headless-android（Apache-2.0）和 ShadowAuto。
 * 用户要的效果：AI 在虚拟屏上操作，真实屏幕完全不受影响。
 */
public class XiaobanDisplayService extends IXiaobanDisplay.Stub {

    private Context ctx;
    private VirtualDisplay display;
    private ImageReader reader;
    private Surface surface;
    private int displayId = -1;
    private int width, height, dpi;
    private long frameCount = 0;
    private String lastError = "";

    // 输入注入用的反射方法
    private Object inputManager;
    private Method injectMethod;
    private Method setDisplayIdMethod;
    private String inputProblem;

    /** Shizuku 反射实例化用（无参）。 */
    public XiaobanDisplayService() {
        this(pickContext());
    }

    public XiaobanDisplayService(Context context) {
        this.ctx = context;
        prepareInput();
    }

    /** 在 UserService 进程里拿到 Context。 */
    private static Context pickContext() {
        try {
            Class<?> at = Class.forName("android.app.ActivityThread");
            java.lang.reflect.Method m = at.getMethod("currentApplication");
            Object app = m.invoke(null);
            if (app instanceof Context) return (Context) app;
        } catch (Throwable ignored) {
        }
        try {
            Class<?> at = Class.forName("android.app.ActivityThread");
            java.lang.reflect.Method m = at.getMethod("currentActivityThread");
            Object t = m.invoke(null);
            if (t != null) {
                java.lang.reflect.Field f = at.getDeclaredField("mInitialApplication");
                f.setAccessible(true);
                Object app = f.get(t);
                if (app instanceof Context) return (Context) app;
            }
        } catch (Throwable ignored) {
        }
        return null;
    }

    private void prepareInput() {
        try {
            inputManager = ctx.getSystemService(Context.INPUT_SERVICE);
            if (inputManager == null) throw new IllegalStateException("no INPUT_SERVICE");
            injectMethod = inputManager.getClass().getMethod("injectInputEvent", InputEvent.class, int.class);
            setDisplayIdMethod = InputEvent.class.getMethod("setDisplayId", int.class);
        } catch (Throwable e) {
            inputProblem = e.getClass().getSimpleName() + ": " + e.getMessage();
        }
    }

    /** 取隐藏的 flag 常量（不同 Android 版本名字可能不同）。 */
    private static int hiddenFlag(String name) {
        try {
            return DisplayManager.class.getField(name).getInt(null);
        } catch (Throwable e) {
            return 0;
        }
    }

    @Override
    public int createDisplay(int w, int h, int d) {
        releaseDisplay();
        width = Math.max(240, Math.min(2160, w));
        height = Math.max(240, Math.min(3840, h));
        dpi = Math.max(120, Math.min(640, d));

        try {
            reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 3);
            reader.setOnImageAvailableListener(new ImageReader.OnImageAvailableListener() {
                @Override
                public void onImageAvailable(ImageReader r) {
                    Image img = null;
                    try {
                        img = r.acquireLatestImage();
                        if (img != null) frameCount++;
                    } catch (Throwable ignored) {
                    } finally {
                        if (img != null) try { img.close(); } catch (Throwable ignored) {}
                    }
                }
            }, null);
            surface = reader.getSurface();
        } catch (Throwable e) {
            return -1;
        }

        DisplayManager dm = (DisplayManager) ctx.getSystemService(Context.DISPLAY_SERVICE);
        if (dm == null) return -1;

        int base = DisplayManager.VIRTUAL_DISPLAY_FLAG_PUBLIC
                | DisplayManager.VIRTUAL_DISPLAY_FLAG_PRESENTATION
                | DisplayManager.VIRTUAL_DISPLAY_FLAG_OWN_CONTENT_ONLY;
        int touch = hiddenFlag("VIRTUAL_DISPLAY_FLAG_SUPPORTS_TOUCH");
        int focus = hiddenFlag("VIRTUAL_DISPLAY_FLAG_OWN_FOCUS");
        int trusted = hiddenFlag("VIRTUAL_DISPLAY_FLAG_TRUSTED");

        // 从"最想要"到"最保守"依次试，不同 ROM 接受的不一样
        int[] candidates = new int[]{
                base | touch | focus | trusted,
                base | touch | focus,
                base | touch,
                base
        };

        for (int flags : candidates) {
            try {
                VirtualDisplay vd = dm.createVirtualDisplay("XiaobanVirtual", width, height, dpi, surface, flags);
                Display target = (vd == null) ? null : vd.getDisplay();
                if (target != null) {
                    display = vd;
                    displayId = target.getDisplayId();
                    return displayId;
                }
                if (vd != null) try { vd.release(); } catch (Throwable ignored) {}
                if (lastError.isEmpty()) lastError = "flags=0x" + Integer.toHexString(flags) + " → 返回 null";
            } catch (Throwable e) {
                lastError = "flags=0x" + Integer.toHexString(flags) + " → "
                        + e.getClass().getSimpleName() + ": " + e.getMessage();
            }
        }
        try { reader.close(); } catch (Throwable ignored) {}
        try { surface.release(); } catch (Throwable ignored) {}
        reader = null;
        surface = null;
        displayId = -1;
        return -1;
    }

    @Override
    public void releaseDisplay() {
        try { if (display != null) display.release(); } catch (Throwable ignored) {}
        try { if (reader != null) reader.close(); } catch (Throwable ignored) {}
        try { if (surface != null) surface.release(); } catch (Throwable ignored) {}
        display = null;
        reader = null;
        surface = null;
        displayId = -1;
    }

    @Override
    public int displayId() {
        return displayId;
    }

    @Override
    public boolean launchApp(String pkg, int id) {
        int d = id >= 0 ? id : displayId;
        if (d < 0) return false;
        try {
            String out = ShellRunner.exec(
                    "am start --display " + d + " -a android.intent.action.MAIN "
                            + "-c android.intent.category.LAUNCHER -p " + pkg, 15000);
            return out != null && out.indexOf("Error") < 0;
        } catch (Throwable e) {
            return false;
        }
    }

    @Override
    public boolean tap(int id, int x, int y) {
        long now = SystemClock.uptimeMillis();
        boolean a = send(id, motion(now, now, MotionEvent.ACTION_DOWN, x, y));
        boolean b = send(id, motion(now, now + 80, MotionEvent.ACTION_UP, x, y));
        return a && b;
    }

    @Override
    public boolean swipe(int id, int x1, int y1, int x2, int y2, int ms) {
        int duration = Math.max(120, ms);
        int steps = Math.max(6, duration / 24);
        long down = SystemClock.uptimeMillis();
        boolean ok = send(id, motion(down, down, MotionEvent.ACTION_DOWN, x1, y1));
        for (int i = 1; i < steps; i++) {
            float p = i / (float) steps;
            int x = Math.round(x1 + (x2 - x1) * p);
            int y = Math.round(y1 + (y2 - y1) * p);
            long t = down + Math.round(duration * p);
            ok = send(id, motion(down, t, MotionEvent.ACTION_MOVE, x, y)) && ok;
            SystemClock.sleep(8);
        }
        return send(id, motion(down, down + duration, MotionEvent.ACTION_UP, x2, y2)) && ok;
    }

    @Override
    public boolean key(int id, int keyCode) {
        long now = SystemClock.uptimeMillis();
        boolean a = send(id, new KeyEvent(now, now, KeyEvent.ACTION_DOWN, keyCode, 0));
        boolean b = send(id, new KeyEvent(now, now + 20, KeyEvent.ACTION_UP, keyCode, 0));
        return a && b;
    }

    @Override
    public boolean text(int id, String value) {
        if (value == null || value.isEmpty()) return true;
        KeyEvent[] events = KeyCharacterMap.load(KeyCharacterMap.VIRTUAL_KEYBOARD)
                .getEvents(value.toCharArray());
        if (events == null || events.length == 0) return false;
        boolean ok = true;
        for (KeyEvent e : events) ok = send(id, e) && ok;
        return ok;
    }

    @Override
    public byte[] screenshot(int id) {
        if (reader == null) return null;
        Image img = null;
        try {
            img = reader.acquireLatestImage();
            if (img == null) return null;
            Image.Plane[] planes = img.getPlanes();
            if (planes.length == 0) return null;
            java.nio.ByteBuffer buf = planes[0].getBuffer();
            int rowStride = planes[0].getRowStride();
            int pixelStride = planes[0].getPixelStride();
            int w = img.getWidth();
            int h = img.getHeight();
            int rowPadding = rowStride - pixelStride * w;
            Bitmap bmp = Bitmap.createBitmap(w + rowPadding / pixelStride, h, Bitmap.Config.ARGB_8888);
            bmp.copyPixelsFromBuffer(buf);
            Bitmap cropped = Bitmap.createBitmap(bmp, 0, 0, w, h);
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            cropped.compress(Bitmap.CompressFormat.PNG, 90, bos);
            bmp.recycle();
            cropped.recycle();
            return bos.toByteArray();
        } catch (Throwable e) {
            return null;
        } finally {
            if (img != null) try { img.close(); } catch (Throwable ignored) {}
        }
    }

    @Override
    public String info() {
        StringBuilder sb = new StringBuilder("{");
        sb.append("\"displayId\":").append(displayId);
        sb.append(",\"width\":").append(width);
        sb.append(",\"height\":").append(height);
        sb.append(",\"dpi\":").append(dpi);
        sb.append(",\"frames\":").append(frameCount);
        sb.append(",\"inputReady\":").append(inputReady());
        if (inputProblem != null) {
            sb.append(",\"inputProblem\":\"").append(inputProblem.replace("\"", "'")).append("\"");
        }
        sb.append(",\"uid\":").append(android.os.Process.myUid());
        if (!lastError.isEmpty()) {
            sb.append(",\"lastError\":\"").append(lastError.replace("\"", "'").replace("\n", " ")).append("\"");
        }
        sb.append("}");
        return sb.toString();
    }

    private boolean inputReady() {
        return inputManager != null && injectMethod != null && setDisplayIdMethod != null;
    }

    private MotionEvent motion(long downTime, long eventTime, int action, int x, int y) {
        MotionEvent e = MotionEvent.obtain(downTime, eventTime, action, x, y,
                1f, 1f, 0, 1f, 1f, 0, 0);
        e.setSource(InputDevice.SOURCE_TOUCHSCREEN);
        return e;
    }

    private boolean send(int id, InputEvent event) {
        if (!inputReady()) return false;
        int d = id >= 0 ? id : displayId;
        try {
            setDisplayIdMethod.invoke(event, d);
            Object r = injectMethod.invoke(inputManager, event, 2); // 2 = WAIT_FOR_FINISH
            return !(r instanceof Boolean) || (Boolean) r;
        } catch (Throwable e) {
            return false;
        } finally {
            try { if (event instanceof MotionEvent) ((MotionEvent) event).recycle(); } catch (Throwable ignored) {}
        }
    }
}

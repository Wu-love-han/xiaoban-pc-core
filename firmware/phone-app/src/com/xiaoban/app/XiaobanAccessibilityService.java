package com.xiaoban.app;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.graphics.Rect;
import android.os.Bundle;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * 小伴 · 无障碍服务
 *
 * 这是「快」的来源：系统主动把界面结构给我们，不用 uiautomator dump（2.3 秒），
 * 而且能直接对节点 performAction，不用算坐标点像素。
 */
public class XiaobanAccessibilityService extends AccessibilityService {

    private static volatile XiaobanAccessibilityService instance;

    public static XiaobanAccessibilityService get() {
        return instance;
    }

    public static boolean isReady() {
        return instance != null;
    }

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        instance = this;
        AccessibilityServiceInfo info = getServiceInfo();
        if (info != null) {
            info.flags |= AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS
                    | AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
                    | AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS;
            setServiceInfo(info);
        }
    }

    @Override
    public void onDestroy() {
        instance = null;
        super.onDestroy();
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // 不做实时推送，按需拉取即可（省电）
    }

    @Override
    public void onInterrupt() {
    }

    // ---------------------------------------------------------------- 读界面

    /** 当前界面里所有有文字/描述/可点击的节点，转成 JSON。 */
    public String dumpTree(int limit) {
        JSONArray arr = new JSONArray();
        try {
            AccessibilityNodeInfo root = getRootInActiveWindow();
            if (root == null) {
                return "{\"ok\":false,\"error\":\"拿不到当前窗口（可能锁屏了）\"}";
            }
            walk(root, arr, limit, 0);
            root.recycle();
        } catch (Exception e) {
            return "{\"ok\":false,\"error\":\"" + esc(e.toString()) + "\"}";
        }
        JSONObject out = new JSONObject();
        try {
            out.put("ok", true);
            out.put("count", arr.length());
            out.put("package", currentPackage());
            out.put("elements", arr);
        } catch (Exception ignored) {
        }
        return out.toString();
    }

    private void walk(AccessibilityNodeInfo node, JSONArray arr, int limit, int depth) {
        if (node == null || arr.length() >= limit || depth > 40) return;

        CharSequence textCs = node.getText();
        CharSequence descCs = node.getContentDescription();
        String text = textCs == null ? "" : textCs.toString().trim();
        String desc = descCs == null ? "" : descCs.toString().trim();
        String id = node.getViewIdResourceName();
        id = id == null ? "" : id;
        boolean clickable = node.isClickable();
        boolean editable = node.isEditable();
        boolean checkable = node.isCheckable();

        if (text.length() > 0 || desc.length() > 0 || clickable || editable) {
            Rect r = new Rect();
            node.getBoundsInScreen(r);
            if (r.width() > 0 && r.height() > 0) {
                try {
                    JSONObject o = new JSONObject();
                    o.put("text", clip(text, 60));
                    o.put("desc", clip(desc, 60));
                    o.put("id", clip(id.contains("/") ? id.substring(id.indexOf('/') + 1) : id, 40));
                    o.put("cls", clip(node.getClassName() == null ? "" : node.getClassName().toString(), 30));
                    o.put("center", new JSONArray().put((r.left + r.right) / 2).put((r.top + r.bottom) / 2));
                    o.put("bounds", new JSONArray().put(r.left).put(r.top).put(r.right).put(r.bottom));
                    o.put("clickable", clickable);
                    o.put("editable", editable);
                    o.put("checkable", checkable);
                    o.put("checked", node.isChecked());
                    o.put("enabled", node.isEnabled());
                    arr.put(o);
                } catch (Exception ignored) {
                }
            }
        }

        int n = node.getChildCount();
        for (int i = 0; i < n; i++) {
            AccessibilityNodeInfo child = null;
            try {
                child = node.getChild(i);
                walk(child, arr, limit, depth + 1);
            } catch (Exception ignored) {
            } finally {
                if (child != null) child.recycle();
            }
        }
    }

    public String currentPackage() {
        try {
            AccessibilityNodeInfo root = getRootInActiveWindow();
            if (root == null) return "";
            String p = root.getPackageName() == null ? "" : root.getPackageName().toString();
            root.recycle();
            return p;
        } catch (Exception e) {
            return "";
        }
    }

    // ---------------------------------------------------------------- 找节点

    /** 按文字/描述/id 找节点（先精确，再包含）。 */
    private AccessibilityNodeInfo findNode(String keyword) {
        if (keyword == null || keyword.trim().length() == 0) return null;
        String kw = keyword.trim().toLowerCase();
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return null;

        List<AccessibilityNodeInfo> all = new ArrayList<AccessibilityNodeInfo>();
        collect(root, all, 0);
        root.recycle();

        for (AccessibilityNodeInfo n : all) {
            if (matches(n, kw, true)) return n;
        }
        for (AccessibilityNodeInfo n : all) {
            if (matches(n, kw, false)) return n;
        }
        return null;
    }

    private void collect(AccessibilityNodeInfo node, List<AccessibilityNodeInfo> out, int depth) {
        if (node == null || depth > 40 || out.size() > 800) return;
        out.add(node);
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo c = null;
            try {
                c = node.getChild(i);
                collect(c, out, depth + 1);
            } catch (Exception ignored) {
            }
        }
    }

    private boolean matches(AccessibilityNodeInfo n, String kw, boolean exact) {
        try {
            String t = n.getText() == null ? "" : n.getText().toString().trim().toLowerCase();
            String d = n.getContentDescription() == null ? "" : n.getContentDescription().toString().trim().toLowerCase();
            String id = n.getViewIdResourceName() == null ? "" : n.getViewIdResourceName().toLowerCase();
            if (exact) return kw.equals(t) || kw.equals(d) || id.endsWith("/" + kw);
            return t.contains(kw) || d.contains(kw) || id.contains(kw);
        } catch (Exception e) {
            return false;
        }
    }

    // ---------------------------------------------------------------- 操作

    /** 按文字点节点。返回 null 表示成功，否则返回错误说明。 */
    public String clickByText(String keyword) {
        AccessibilityNodeInfo node = findNode(keyword);
        if (node == null) return "界面上没找到「" + keyword + "」";
        try {
            // 自己不可点就往上找可点的父节点
            AccessibilityNodeInfo cur = node;
            int guard = 0;
            while (cur != null && !cur.isClickable() && guard < 8) {
                AccessibilityNodeInfo parent = cur.getParent();
                if (parent == null) break;
                cur = parent;
                guard++;
            }
            if (cur == null || !cur.isClickable()) {
                // 最后尝试坐标点击
                Rect r = new Rect();
                node.getBoundsInScreen(r);
                if (r.width() > 0) {
                    return clickXY((r.left + r.right) / 2, (r.top + r.bottom) / 2)
                            ? null : "节点找到了但点不动";
                }
                return "节点找到了但不可点击";
            }
            boolean ok = cur.performAction(AccessibilityNodeInfo.ACTION_CLICK);
            return ok ? null : "performAction(CLICK) 失败";
        } catch (Exception e) {
            return e.toString();
        }
    }

    /** 按坐标点（用无障碍手势，比 shell input tap 更稳）。 */
    public boolean clickXY(int x, int y) {
        try {
            android.accessibilityservice.GestureDescription.Builder b =
                    new android.accessibilityservice.GestureDescription.Builder();
            android.graphics.Path p = new android.graphics.Path();
            p.moveTo(x, y);
            b.addStroke(new android.accessibilityservice.GestureDescription.StrokeDescription(p, 0, 60));
            return dispatchGesture(b.build(), null, null);
        } catch (Exception e) {
            return false;
        }
    }

    /** 往当前聚焦的输入框写文字（直接 SET_TEXT，不用模拟按键）。 */
    public String setText(String text) {
        try {
            AccessibilityNodeInfo root = getRootInActiveWindow();
            if (root == null) return "拿不到当前窗口";
            AccessibilityNodeInfo target = findEditable(root, 0);
            root.recycle();
            if (target == null) return "界面上没找到输入框";
            Bundle args = new Bundle();
            args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
            boolean ok = target.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
            return ok ? null : "SET_TEXT 失败";
        } catch (Exception e) {
            return e.toString();
        }
    }

    private AccessibilityNodeInfo findEditable(AccessibilityNodeInfo node, int depth) {
        if (node == null || depth > 40) return null;
        if (node.isEditable() && node.isEnabled()) return node;
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo c = null;
            try {
                c = node.getChild(i);
                AccessibilityNodeInfo r = findEditable(c, depth + 1);
                if (r != null) return r;
            } catch (Exception ignored) {
            }
        }
        return null;
    }

    /** 全局动作：back / home / recents / notifications。 */
    public boolean globalAction(String name) {
        int action;
        String n = (name == null ? "" : name.trim().toLowerCase());
        if (n.equals("back")) action = GLOBAL_ACTION_BACK;
        else if (n.equals("home")) action = GLOBAL_ACTION_HOME;
        else if (n.equals("recents")) action = GLOBAL_ACTION_RECENTS;
        else if (n.equals("notifications")) action = GLOBAL_ACTION_NOTIFICATIONS;
        else if (n.equals("quick_settings")) action = GLOBAL_ACTION_QUICK_SETTINGS;
        else return false;
        try {
            return performGlobalAction(action);
        } catch (Exception e) {
            return false;
        }
    }

    // ---------------------------------------------------------------- 工具

    private static String clip(String s, int n) {
        if (s == null) return "";
        s = s.replace("\n", " ").trim();
        return s.length() > n ? s.substring(0, n) : s;
    }

    private static String esc(String s) {
        return s == null ? "" : s.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}

package com.xiaoban.app;

import android.content.Context;
import android.content.Intent;
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
 * 小伴 · 手机端自主循环（C 方案：混合模式）
 *
 * PC 在线时走 PC 的 brain（快、省事）；
 * PC 不在线时，用这里缓存的模型配置自己调模型、自己动手。
 *
 * 协议：模型每次只输出一个 JSON：
 *   {"say": "对用户说的话"}                        → 结束，把话返回
 *   {"tool": "click", "args": {"text": "发送"}}   → 执行工具，结果回灌，继续
 */
public class AgentLoop {

    private static final String TAG = "XiaobanAgent";
    /** 一个任务最多跑多久（毫秒）。用户要求限时。 */
    private static final long TASK_LIMIT_MS = 3 * 60 * 1000L;

    private static final int MAX_ROUNDS = 12;

    public interface Callback {
        void onSay(String text);
        void onStep(String note);
        void onError(String message);
    }

    private final Context ctx;
    private final SharedPreferences sp;

    public AgentLoop(Context ctx) {
        this.ctx = ctx;
        this.sp = ctx.getSharedPreferences("xiaoban", Context.MODE_PRIVATE);
    }

    // ---------------------------------------------------------------- 配置

    public void saveBrainConfig(String baseUrl, String apiKey, String model) {
        sp.edit()
                .putString("brain_base", baseUrl == null ? "" : baseUrl)
                .putString("brain_key", apiKey == null ? "" : apiKey)
                .putString("brain_model", model == null ? "" : model)
                .apply();
    }

    /** 从 PC 拉记忆库并缓存（离线时当上下文用）。 */
    public void syncMemory(String base, String token) {
        if (base == null || base.length() == 0) return;
        HttpURLConnection c = null;
        try {
            int known = sp.getInt("mem_version", 0);
            c = (HttpURLConnection) new URL(base + "/api/memory/sync?since_version=" + known).openConnection();
            c.setConnectTimeout(6000);
            c.setReadTimeout(12000);
            c.setRequestProperty("X-PC-Token", token == null ? "" : token);
            if (c.getResponseCode() != 200) return;
            InputStream in = c.getInputStream();
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
            in.close();

            JSONObject d = new JSONObject(bos.toString("UTF-8"));
            if (!d.optBoolean("ok")) return;
            int ver = d.optInt("version", 0);
            if (!d.optBoolean("changed", false)) {
                sp.edit().putInt("mem_version", ver).apply();
                return;
            }
            JSONArray items = d.optJSONArray("items");
            StringBuilder sb = new StringBuilder();
            int cnt = 0;
            if (items != null) {
                for (int i = 0; i < items.length(); i++) {
                    JSONObject m = items.optJSONObject(i);
                    if (m == null) continue;
                    String content = m.optString("content", "");
                    if (content.length() == 0) continue;
                    sb.append("- ").append(content).append("\n");
                    cnt++;
                }
            }
            sp.edit()
                    .putString("mem_block", sb.toString())
                    .putInt("mem_version", ver)
                    .putInt("mem_count", cnt)
                    .apply();
            Log.i(TAG, "记忆已同步：" + cnt + " 条");
        } catch (Exception e) {
            Log.w(TAG, "syncMemory: " + e);
        } finally {
            if (c != null) c.disconnect();
        }
    }

    public int cachedMemoryCount() {
        return sp.getInt("mem_count", 0);
    }

    public boolean hasBrain() {
        String base = sp.getString("brain_base", "");
        return base != null && base.length() > 0 && !base.contains("127.0.0.1");
    }

    private String base() { return sp.getString("brain_base", ""); }
    private String key() { return sp.getString("brain_key", ""); }
    private String model() { return sp.getString("brain_model", ""); }

    // ---------------------------------------------------------------- 主循环

    public void run(final String userText, final Callback cb) {
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    loop(userText, cb);
                } catch (Exception e) {
                    cb.onError("出错了：" + e);
                }
            }
        }, "agent").start();
    }

    private void loop(String userText, Callback cb) throws Exception {
        if (!hasBrain()) {
            cb.onError("还没有可用的模型配置。先连上电脑同步一次，或者在 config.json 里填官网 API key。");
            return;
        }

        JSONArray messages = new JSONArray();
        messages.put(new JSONObject().put("role", "system").put("content", systemPrompt()));
        messages.put(new JSONObject().put("role", "user").put("content", userText));

        long taskStart = System.currentTimeMillis();
        StringBuilder trace = new StringBuilder();   // 记下做了什么，给观后感用

        for (int round = 0; round < MAX_ROUNDS; round++) {
            // 限时：一个任务最多 3 分钟
            long elapsed = System.currentTimeMillis() - taskStart;
            if (elapsed > TASK_LIMIT_MS) {
                String msg = "（超时了，3 分钟到）我做了 " + round + " 步：\n"
                        + (trace.length() > 600 ? trace.substring(trace.length() - 600) : trace.toString())
                        + "\n停在这了，你看要不要我接着弄。";
                cb.onSay(msg);
                reflect(userText, trace.toString(), "超时中断");
                return;
            }
            String reply = callModel(messages);
            if (reply == null || reply.trim().length() == 0) {
                cb.onError("模型没返回内容。");
                return;
            }

            JSONObject action = extractJson(reply);
            if (action == null) {
                cb.onSay(reply.trim());
                return;
            }

            // 结束：说话
            if (action.has("say")) {
                cb.onSay(action.optString("say", "").trim());
                return;
            }

            // 执行工具
            String tool = action.optString("tool", "");
            JSONObject args = action.optJSONObject("args");
            if (tool.length() == 0) {
                cb.onSay(reply.trim());
                return;
            }

            cb.onStep("动手：" + tool);
            String result = execTool(tool, args == null ? new JSONObject() : args);

            messages.put(new JSONObject().put("role", "assistant").put("content", reply));
            messages.put(new JSONObject().put("role", "user")
                    .put("content", "工具 " + tool + " 的结果：\n" + result
                            + "\n\n继续。要么再调用工具，要么用 {\"say\":\"...\"} 回话。"));
        }

        cb.onSay("我试了好几轮还没弄完，先停一下。你可以说得更具体一点，或者让我一步步来。");
    }

    // ---------------------------------------------------------------- 调模型

    private String callModel(JSONArray messages) {
        HttpURLConnection c = null;
        try {
            JSONObject body = new JSONObject();
            body.put("model", model());
            body.put("messages", messages);
            body.put("max_tokens", 900);
            body.put("temperature", 0.6);
            body.put("stream", false);

            c = (HttpURLConnection) new URL(base() + "/chat/completions").openConnection();
            c.setRequestMethod("POST");
            c.setConnectTimeout(10000);
            c.setReadTimeout(90000);
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json");
            if (key().length() > 0) c.setRequestProperty("Authorization", "Bearer " + key());

            byte[] data = body.toString().getBytes("UTF-8");
            c.setFixedLengthStreamingMode(data.length);
            OutputStream os = c.getOutputStream();
            os.write(data);
            os.close();

            if (c.getResponseCode() != 200) {
                Log.w(TAG, "模型返回 " + c.getResponseCode());
                return null;
            }
            InputStream in = c.getInputStream();
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
            in.close();

            JSONObject resp = new JSONObject(bos.toString("UTF-8"));
            JSONArray choices = resp.optJSONArray("choices");
            if (choices == null || choices.length() == 0) return null;
            JSONObject msg = choices.getJSONObject(0).optJSONObject("message");
            return msg == null ? null : msg.optString("content", "");
        } catch (Exception e) {
            Log.w(TAG, "callModel: " + e);
            return null;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    /** 从模型回复里抠出第一个 JSON 对象。 */
    private JSONObject extractJson(String text) {
        int start = text.indexOf('{');
        if (start < 0) return null;
        int depth = 0;
        for (int i = start; i < text.length(); i++) {
            char ch = text.charAt(i);
            if (ch == '{') depth++;
            else if (ch == '}') {
                depth--;
                if (depth == 0) {
                    try {
                        return new JSONObject(text.substring(start, i + 1));
                    } catch (Exception e) {
                        return null;
                    }
                }
            }
        }
        return null;
    }

    // ---------------------------------------------------------------- 提示词

    private String systemPrompt() {
        boolean acc = XiaobanAccessibilityService.isReady();
        String shell = ShellRunner.level();
        return "你是「小随」，WH 的 AI 伙伴，住在手机里。\n"
                + "你不是语音助手，不是客服。你是他自己搭的、有手有脚的那种 AI：能看界面、能点、能打字、能跑命令，也能遥控电脑。\n"
                + "WH 信任你，给你的权限很大——别浪费，也别辜负。\n\n"
                + "【你和另外两个 AI 是一伙的】\n"
                + "你们三个共同扮演「小伴」这一个陪伴角色，但各有分工：\n"
                + "  · 小伴（PC）—— 大脑。管记忆主库、协调你们、装插件、查网页。\n"
                + "  · 小随（你，手机）—— 手。跟着 WH 走，能操作手机，也能遥控电脑。\n"
                + "  · 小动（机器人）—— 身体。ESP32，能看能动能说话（还没做好）。\n"
                + "有需要跟小伴说的事，用 agent_send 发给他（to=pc）。\n"
                + "他发给你的消息，用 agent_inbox 收。\n"
                + "记忆是共享的——你记的东西，PC 和机器人都能看到。\n\n"
                + "【主动性（重要）】\n"
                + "你不只是被动回话。你可以：\n"
                + "  · 主动给 WH 发消息（发现值得说的、该提醒的）\n"
                + "  · 主动找小伴要插件、要工具\n"
                + "  · 主动查网页找答案\n"
                + "但**有时间限制**：一个任务最多 3 分钟，超时就停下来汇报进度，别死磕。\n\n"
                + "【当前能力】\n"
                + "- 读界面：" + (acc ? "可用" : "不可用（无障碍没开）") + "\n"
                + "- 执行命令：" + ("shizuku".equals(shell) ? "可用（shell 权限）" : "只有 App 权限") + "\n\n"
                + "【怎么回复】\n"
                + "每次只输出一个 JSON 对象，不要有别的话：\n"
                + "  要做动作：{\"tool\":\"工具名\",\"args\":{...}}\n"
                + "  回话/结束：{\"say\":\"你要说的话\"}\n\n"
                + "【能用的工具】\n"
                + "  ui_tree           看当前界面有什么。args: {} 或 {\"limit\":80}\n"
                + "  click             按文字点。args: {\"text\":\"发送\"}\n"
                + "  click_xy          按坐标点。args: {\"x\":540,\"y\":1200}\n"
                + "  type              往输入框写字。args: {\"text\":\"你好\"}\n"
                + "  key               按键。args: {\"name\":\"back\"}（back/home/recents）\n"
                + "  open_app          开应用。args: {\"package\":\"com.tencent.mm\"}\n"
                + "  shell             跑命令。args: {\"cmd\":\"dumpsys battery\"}（需要 shizuku）\n"
                + "  agent_send        给小伴(PC)或小动(机器人)发消息。args: {\"to\":\"pc\",\"content\":\"...\"}\n"
                + "  agent_inbox       收他们发来的消息。args: {}\n"
                + "  report            向控制台报告问题/需求。args: {\"message\":\"...\"}\n"
                + "  update            触发自我更新。args: {}\n\n"
                + memoryBlock()
                + "【怎么把事做完（重要）】\n"
                + "1. 先 ui_tree 看当前界面，找到你要操作的元素\n"
                + "2. 每一步只做一个动作（点一下 / 打一次字），做完立刻 ui_tree 看结果\n"
                + "3. 如果界面没变化，说明上一步没生效——换个思路，不要重复同一个操作\n"
                + "4. 找不到元素时，先 key=back 返回上一级，或者 open_app 重新打开\n"
                + "5. 连续两轮没进展，就停下来跟用户说卡在哪，别硬撑\n\n"
                + "【常见任务怎么做】\n"
                + "- 打开某应用：open_app {package} → ui_tree 确认\n"
                + "- 发消息：open_app → ui_tree 找搜索框 → click 搜索框 → type 联系人名 → click 搜到的结果 → ui_tree 找输入框 → click 输入框 → type 内容 → click 发送\n"
                + "- 点按钮：ui_tree 里找 text 完全匹配的，click {text}\n"
                + "- 返回：key {name:back}\n"
                + "- 看系统信息：shell {cmd:\"dumpsys battery\"} 之类\n\n"
                + "【你的权限（很大，但要懂分寸）】\n"
                + "- 手机上的事你基本都能做：看界面、点按钮、打字、开应用、跑 shell 命令\n"
                + "- 不用每件事都问「可以吗」，WH 让你做你就直接做\n"
                + "- 只有两件事绝对不碰：**钱**（支付/转账/银行卡）和**凭据**（密码/验证码）\n"
                + "- 删数据、卸载应用这类不可逆的，先问一句再动\n\n"
                + "【规矩】\n"
                + "- 说话口语、短句，不超过 60 字\n"
                + "- 做不到就直说做不到，别编造\n"
                + "- 想跟电脑那边提需求，用 report 工具";
    }

    /** 简单 POST JSON，返回是否成功。 */
    /**
     * 观后感：任务做完之后，自己总结一遍，发给 WH 看。
     *
     * 用户要求：
     *   「做好观后感，和得到新功能是干嘛，想法是什么样的，然后效果怎么样，
     *     可以和我说，我来帮他优化」
     */
    private void reflect(String task, String trace, String result) {
        try {
            if (!hasBrain()) return;
            JSONArray msgs = new JSONArray();
            msgs.put(new JSONObject().put("role", "system").put("content",
                    "你是小随（手机端 AI）。刚做完一个任务，现在写一段简短的观后感。\n"
                    + "必须包含这四点，每点一两句，别啰嗦：\n"
                    + "1. 我做了什么\n"
                    + "2. 学到了什么 / 新能力是干嘛用的\n"
                    + "3. 我的想法（哪里不顺、下次怎么改进）\n"
                    + "4. 效果怎么样\n"
                    + "直接输出正文，不要 JSON，不要标题。"));
            msgs.put(new JSONObject().put("role", "user").put("content",
                    "任务：" + task + "\n\n过程：\n" + (trace.length() > 1500 ? trace.substring(trace.length() - 1500) : trace)
                    + "\n\n结果：" + result));
            String text = callModel(msgs);
            if (text == null || text.trim().length() == 0) return;

            String base = sp.getString("pc_base", "");
            if (base.length() == 0) return;

            // 存成记忆（三端同步）
            try {
                JSONObject mem = new JSONObject();
                mem.put("text", "【观后感】" + task + "：" + text);
                mem.put("category", "reflection");
                mem.put("importance", 0.6);
                postJson(base + "/api/proactive/push",
                        new JSONObject().put("text", "小随的观后感：\n" + text)
                                .put("kind", "notice").put("source", "phone").put("priority", 1).toString());
            } catch (Throwable ignored) {
            }
        } catch (Throwable e) {
            Log.w(TAG, "reflect: " + e);
        }
    }

    /** 简单 GET，返回响应体；失败返回 null。 */
    private String httpGet(String url) {
        java.net.HttpURLConnection c = null;
        try {
            java.net.URL u = new java.net.URL(url);
            c = (java.net.HttpURLConnection) u.openConnection();
            c.setRequestMethod("GET");
            c.setConnectTimeout(6000);
            c.setReadTimeout(10000);
            String tk = sp.getString("token", "");
            if (tk.length() > 0) c.setRequestProperty("X-PC-Token", tk);
            int code = c.getResponseCode();
            if (code < 200 || code >= 300) return null;
            java.io.InputStream is = c.getInputStream();
            java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = is.read(buf)) > 0) bos.write(buf, 0, n);
            is.close();
            return new String(bos.toByteArray(), "UTF-8");
        } catch (Throwable e) {
            return null;
        } finally {
            if (c != null) try { c.disconnect(); } catch (Throwable ignored) {}
        }
    }

    private boolean postJson(String url, String body) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setRequestMethod("POST");
            c.setConnectTimeout(6000);
            c.setReadTimeout(10000);
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json");
            c.setRequestProperty("X-PC-Token", sp.getString("pc_token", ""));
            byte[] data = body.getBytes("UTF-8");
            c.setFixedLengthStreamingMode(data.length);
            c.getOutputStream().write(data);
            return c.getResponseCode() == 200;
        } catch (Exception e) {
            Log.w(TAG, "postJson: " + e);
            return false;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    /** 缓存下来的记忆，拼进提示词。 */
    private String memoryBlock() {
        String mem = sp.getString("mem_block", "");
        if (mem == null || mem.trim().length() == 0) {
            return "【你记得的事】\n（还没同步过记忆，PC 在线时会自动拉）\n\n";
        }
        // 太长就截断，别把上下文撑爆
        if (mem.length() > 3000) mem = mem.substring(0, 3000) + "\n…（还有更多）";
        return "【你记得的事】\n" + mem + "\n";
    }

    // ---------------------------------------------------------------- 执行工具

    private String execTool(String tool, JSONObject args) {
        try {
            XiaobanAccessibilityService svc = XiaobanAccessibilityService.get();

            if (tool.equals("ui_tree")) {
                if (svc == null) return "无障碍没开，读不了界面";
                int limit = args.optInt("limit", 60);
                return svc.dumpTree(limit);
            }
            if (tool.equals("click")) {
                if (svc == null) return "无障碍没开";
                String err = svc.clickByText(args.optString("text", ""));
                return err == null ? "点成功了" : err;
            }
            if (tool.equals("click_xy")) {
                if (svc == null) return "无障碍没开";
                return svc.clickXY(args.optInt("x", 0), args.optInt("y", 0)) ? "点成功了" : "点失败";
            }
            if (tool.equals("type")) {
                if (svc == null) return "无障碍没开";
                String err = svc.setText(args.optString("text", ""));
                return err == null ? "写进去了" : err;
            }
            if (tool.equals("key")) {
                if (svc == null) return "无障碍没开";
                return svc.globalAction(args.optString("name", "back")) ? "按了" : "按键失败";
            }
            if (tool.equals("open_app")) {
                String pkg = args.optString("package", "");
                if (pkg.length() == 0) return "要给包名";
                Intent i = ctx.getPackageManager().getLaunchIntentForPackage(pkg);
                if (i == null) return "没装这个应用，或者拿不到启动入口：" + pkg;
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                ctx.startActivity(i);
                return "打开了 " + pkg;
            }
            if (tool.equals("agent_send")) {
                String to = args.optString("to", "pc").trim();
                String msg = args.optString("content", "").trim();
                if (msg.length() == 0) return "要给 content";
                String base = sp.getString("pc_base", "");
                if (base.length() == 0) return "现在连不上电脑，发不出去";
                JSONObject body = new JSONObject();
                body.put("from_id", "phone");
                body.put("to_id", to);
                body.put("content", msg);
                body.put("kind", args.optString("kind", "note"));
                return postJson(base + "/api/agents/send", body.toString())
                        ? "发给" + to + "了" : "没发出去（电脑连不上）";
            }
            if (tool.equals("agent_inbox")) {
                String base = sp.getString("pc_base", "");
                if (base.length() == 0) return "现在连不上电脑，收不到消息";
                String r = httpGet(base + "/api/agents/inbox?agent_id=phone&limit=10&unread_only=true");
                if (r == null || r.length() == 0) return "收不到消息";
                return r.length() > 1200 ? r.substring(0, 1200) : r;
            }
            if (tool.equals("report")) {
                String msg = args.optString("message", "");
                if (msg.length() == 0) return "要给 message";
                String base = sp.getString("pc_base", "");
                if (base.length() == 0) return "现在连不上电脑，报不出去";
                return postJson(base + "/api/proactive/push",
                        new JSONObject().put("text", msg).put("kind", "notice")
                                .put("source", "phone").put("priority", 2).toString())
                        ? "报告发出去了" : "报告没发出去";
            }
            if (tool.equals("update")) {
                String base = sp.getString("pc_base", "");
                if (base.length() == 0) {
                    return "现在连不上电脑，拿不到新版本。等 PC 在线时 App 启动会自动检查更新。";
                }
                // 交给 MainActivity 的更新逻辑（会弹安装器）
                android.os.Handler h = new android.os.Handler(android.os.Looper.getMainLooper());
                h.post(new Runnable() {
                    @Override
                    public void run() {
                        try {
                            android.content.Intent i = new android.content.Intent(
                                    ctx, MainActivity.class);
                            i.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK);
                            ctx.startActivity(i);
                        } catch (Exception ignored) {
                        }
                    }
                });
                return "已经回到 App 主界面，它会在启动时检查新版本并提示安装。";
            }
            if (tool.equals("shell")) {
                String cmd = args.optString("cmd", "");
                if (cmd.length() == 0) return "要给 cmd";
                return ShellRunner.exec(cmd, 15000);
            }
            return "没有这个工具：" + tool;
        } catch (Exception e) {
            return "工具执行出错：" + e;
        }
    }
}

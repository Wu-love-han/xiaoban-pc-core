"""真实 HTTP 联调：打 http://127.0.0.1:8770，走完整 SSE。"""
import json, httpx

BASE="http://127.0.0.1:8770"

def sse_chat(text, session_id=None):
    payload={"text":text}
    if session_id: payload["session_id"]=session_id
    events=[]; buf=[]; tools=[]
    with httpx.stream("POST", BASE+"/api/chat", json=payload, timeout=180) as r:
        assert r.status_code==200, r.status_code
        ctype=r.headers.get("content-type","")
        cur_ev=None
        for line in r.iter_lines():
            if not line: 
                cur_ev=None; continue
            if line.startswith(":"): continue
            if line.startswith("event:"): cur_ev=line[6:].strip()
            elif line.startswith("data:"):
                d=json.loads(line[5:].strip())
                events.append(cur_ev)
                if cur_ev=="content": buf.append(d.get("text",""))
                elif cur_ev=="tool_call": tools.append(f'{d["name"]}({json.dumps(d["args"],ensure_ascii=False)})')
                elif cur_ev=="session": session_id=d["session_id"]
                elif cur_ev=="error": print("   ERROR:", d)
    return session_id, events, tools, "".join(buf), ctype

print("="*74)
print("1) 健康检查")
h=httpx.get(BASE+"/api/health", timeout=10).json()
print("  ", {k:h.get(k) for k in ("ok","provider","model","tools","brain_ready")})

print("\n2) 工具清单")
t=httpx.get(BASE+"/api/tools", timeout=10).json()
print("   count:", t.get("count"), " danger:", [x["name"] for x in t["items"] if x["danger"]])

print("\n3) 首页")
r=httpx.get(BASE+"/", timeout=10)
print("   status:", r.status_code, "bytes:", len(r.text), "has 小伴:", "小伴" in r.text)

print("\n"+"="*74)
sid=None
for text, expect in [
    ("今天好累啊", "纯聊天·零工具"),
    ("看看 E:\\WH 里有什么", "指令·调 pc.list_dir"),
]:
    print(f"\n用户：{text}    （{expect}）")
    sid, evs, tools, reply, ctype = sse_chat(text, sid)
    print(f"  会话: {sid}")
    print(f"  content-type: {ctype}")
    print(f"  事件: {evs}")
    print(f"  工具: {tools or '（无）'}")
    print(f"  回复: {reply[:150]}")

print("\n"+"="*74)
print("4) 落库证据（tool_calls 就是「判成指令」的凭据）")
msgs=httpx.get(f"{BASE}/api/sessions/{sid}/messages", timeout=10).json()["items"]
for m in msgs:
    if m["role"]=="assistant":
        print(f'  msg#{m["id"]}  tool_calls={len(m["tool_calls"])}  {m["content"][:45]!r}')

print("\n5) 事件流水")
ev=httpx.get(f"{BASE}/api/events?limit=8&session_id={sid}", timeout=10).json()["items"]
print("  ", [e["kind"] for e in ev])

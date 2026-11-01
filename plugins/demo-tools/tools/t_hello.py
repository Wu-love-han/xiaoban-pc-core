TOOL = {
    "name": "pc.demo.hello",
    "title": "打招呼",
    "desc": "跟指定的人说你好",
    "danger": False,
    "params": {"type": "object", "properties": {"who": {"type": "string", "description": "对谁说"}}},
    "run": lambda args, ctx: {"ok": True, "output": f"你好，{args.get('who', '世界')}！"},
}

import datetime
TOOL = {
    "name": "pc.demo.now",
    "title": "现在几点",
    "desc": "返回当前日期时间",
    "danger": False,
    "params": {"type": "object", "properties": {}},
    "run": lambda args, ctx: {"ok": True, "output": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
}

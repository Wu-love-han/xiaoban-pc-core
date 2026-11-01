"""sys.time：当前时间、时区、星期。

机器上的时间可能和用户心里想的不一样（时区错、时钟漂移），
所以把「本地时间 + 时区偏移 + 时间戳」一次说清，别让模型自己猜。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from . import _common as C

_WEEK = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def run(args: dict, ctx: Any) -> dict:
    now = datetime.now()
    local = now.astimezone()
    off = local.utcoffset()

    off_s = "UTC"
    if off is not None:
        total = int(off.total_seconds())
        sign = "+" if total >= 0 else "-"
        total = abs(total)
        off_s = f"UTC{sign}{total // 3600:02d}:{total % 3600 // 60:02d}"

    tzname = time.tzname[0] if time.tzname else ""
    out = (
        f"现在 {local.strftime('%Y-%m-%d %H:%M:%S')}，"
        f"{_WEEK[local.weekday()]}，时区 {off_s}"
        + (f"（{tzname}）" if tzname else "")
        + f"，时间戳 {int(now.timestamp())}"
    )
    return C.ok(out)


TOOL = {
    "name": "sys.time",
    "title": "看现在几点",
    "desc": "查当前的日期、时间、星期和时区。需要知道今天几号、现在几点、离某个时间还有多久时用。",
    "danger": False,
    "params": {"type": "object", "properties": {}},
    "run": C.guard(run),
}

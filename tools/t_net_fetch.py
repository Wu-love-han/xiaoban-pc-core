"""net.fetch：抓网页正文。

用 httpx + 手写 HTML 剥离，不引入 bs4/lxml——工具层只依赖 httpx，
少一个三方包就少一个「这台机器没装」的失败面。

剥离顺序很重要：
1. 先干掉 script/style/noscript/svg/iframe/head 整段（包括内容），
   否则 JS 代码会混进正文，读起来全是噪声。
2. 再去标签，HTML 实体反转义。
3. 最后按空行折叠，压成一段段文本。

正文上限 2000 字（比 output 的 400 字宽），超出的部分留在 data.text 里，
output 只放前面能塞下的部分。
"""

from __future__ import annotations

import html as html_mod
import re
from typing import Any
from urllib.parse import urlparse

from . import _common as C

MAX_CHARS = 2000
TIMEOUT_S = 20.0
MAX_RAW = 3 * 1024 * 1024  # 原始 HTML 最多收 3MB，防止下到一个大文件
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_DROP_BLOCKS = re.compile(
    r"<(script|style|noscript|svg|iframe|head|template|canvas)\b[^>]*>.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_COMMENTS = re.compile(r"<!--.*?-->", re.DOTALL)
_BLOCK_TAGS = re.compile(
    r"</?(p|div|br|hr|li|ul|ol|tr|td|th|table|h[1-6]|section|article|header|footer|"
    r"nav|aside|blockquote|pre|figure|figcaption)\b[^>]*>",
    re.IGNORECASE,
)
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\u00a0\u3000]+")
_BLANKS = re.compile(r"\n{3,}")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_CHARSET = re.compile(rb'charset=["\']?([\w\-]+)', re.IGNORECASE)


def _decode(raw: bytes, header_charset: str) -> str:
    """编码：响应头 → <meta charset> → utf-8 → gbk → latin-1。"""
    tried: list[str] = []
    for enc in (header_charset,):
        if enc:
            tried.append(enc)
    m = _META_CHARSET.search(raw[:4096])
    if m:
        try:
            tried.append(m.group(1).decode("ascii", "ignore"))
        except Exception:  # noqa: BLE001
            pass
    tried += ["utf-8", "gbk"]

    seen = set()
    for enc in tried:
        e = (enc or "").strip().lower()
        if not e or e in seen:
            continue
        seen.add(e)
        try:
            return raw.decode(e)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def html_to_text(markup: str) -> tuple[str, str]:
    """返回 (标题, 正文)。"""
    title = ""
    m = _TITLE.search(markup)
    if m:
        title = html_mod.unescape(_TAGS.sub("", m.group(1))).strip()

    s = _COMMENTS.sub(" ", markup)
    s = _DROP_BLOCKS.sub(" ", s)
    s = _BLOCK_TAGS.sub("\n", s)
    s = _TAGS.sub(" ", s)
    s = html_mod.unescape(s)
    s = _SPACES.sub(" ", s)

    lines = [ln.strip() for ln in s.split("\n")]
    body = "\n".join(ln for ln in lines if ln)
    body = _BLANKS.sub("\n\n", body)
    return title, body.strip()


def run(args: dict, ctx: Any) -> dict:
    url = str(args.get("url") or args.get("target") or "").strip()
    if not url:
        return C.fail("要抓哪个网址呢？url 是空的。", "MissingArg: url")

    if not re.match(r"^https?://", url, re.IGNORECASE):
        if re.match(r"^[\w\-]+(\.[\w\-]+)+", url):
            url = "https://" + url  # 模型经常漏协议头
        else:
            return C.fail(f"「{url}」不像一个网址，我只抓 http/https 的页面。", "BadUrl")

    limit = int(args.get("max_chars") or MAX_CHARS)
    limit = max(200, min(limit, MAX_CHARS))

    try:
        import httpx  # type: ignore
    except ImportError:
        return C.fail(
            "这台机器的 Python 里没装 httpx，抓网页用不了。",
            "ImportError: httpx",
        )

    try:
        with httpx.Client(
            timeout=TIMEOUT_S,
            follow_redirects=True,
            headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        ) as cli:
            with cli.stream("GET", url) as r:
                ctype = (r.headers.get("content-type") or "").lower()
                if r.status_code >= 400:
                    return C.fail(
                        f"{url} 返回了 {r.status_code}，抓不到内容。", f"HTTP {r.status_code}"
                    )
                chunks: list[bytes] = []
                total = 0
                for chunk in r.iter_bytes():
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= MAX_RAW:
                        break
                raw = b"".join(chunks)
                charset = r.charset_encoding or ""
                final_url = str(r.url)
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        hint = "（网络不通或超时）" if "Timeout" in name or "Connect" in name else ""
        return C.fail(f"抓 {url} 失败了{hint}：{name}。", f"{name}: {exc}")

    if not raw:
        return C.fail(f"{url} 抓回来是空的。", "EmptyResponse")

    # 非 HTML（纯文本/json）：直接用
    if "html" not in ctype and "xml" not in ctype:
        text = _decode(raw, charset).strip()
        title = ""
    else:
        title, text = html_to_text(_decode(raw, charset))

    if not text:
        return C.fail(f"{url} 抓到了，但剥完标签一个字都没剩下（可能是纯 JS 渲染的页面）。", "NoText")

    host = urlparse(final_url).netloc or url
    head = f"{title or host}（{host}，{len(text)} 字）"
    room = C.MAX_OUT - len(head) - 30
    if len(text) <= room:
        out = f"{head}\n{text}"
    else:
        out = f"{head}\n{text[:max(0, room)]}\n…（还有 {len(text) - room} 字没放出来）"

    return C.ok(
        out,
        url=final_url,
        title=title,
        chars=len(text),
        text=text[:limit],
        content_type=ctype,
    )


TOOL = {
    "name": "net.fetch",
    "title": "抓网页正文",
    "desc": "打开一个网址，把页面里的正文文字抓回来（去掉脚本和标签，最多 2000 字）。看一篇具体的文章/文档/网页时用。",
    "danger": False,
    "params": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要抓的网址，http:// 或 https://"},
            "max_chars": {
                "type": "integer",
                "description": f"正文最多保留多少字（200-{MAX_CHARS}，默认 {MAX_CHARS}）",
            },
        },
        "required": ["url"],
    },
    "run": C.guard(run),
}

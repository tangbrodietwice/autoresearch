"""Workspace commands: settings."""
from .common import uid
from urllib.parse import urlparse


def tool(self, db, d):
    def s(key, default="", required=False):
        return self.string(d, key, default, required)

    kind=s("kind",required=True)
    target=s("target",required=True)
    if kind not in ("link","command"): raise ValueError("未知工具类型。")
    if kind=="link" and (urlparse(target).scheme not in ("http","https") or not urlparse(target).hostname):
        raise ValueError("请输入有效的 HTTP/HTTPS 链接。")
    return self.put(db,"tool",dict(id=uid(),name=s("name",required=True),kind=kind,target=target))


def settings(self, db, d):
    delay, slots=d.get("delay"),d.get("slots")
    if type(delay) not in (int,float) or not .2<=delay<=60 or type(slots) is not int or not 1<=slots<=8:
        raise ValueError("模拟时长为 0.2–60 秒，并发为 1–8。")
    row=self.p.get(db,"settings","active")
    row.update(delay=delay,slots=slots)
    self.p.put(db,"settings","active",row)
    return row

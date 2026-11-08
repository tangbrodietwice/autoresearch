"""Use the macOS system proxy for CLI children that do not inherit GUI networking."""
import os
import platform
import re
import subprocess


def codex_environment():
    env = os.environ.copy()
    if platform.system() != "Darwin" or any(env.get(key) for key in (
        "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"
    )):
        return env
    try:
        result = subprocess.run(
            ["/usr/sbin/scutil", "--proxy"], capture_output=True, text=True, check=True, timeout=2
        )
    except (OSError, subprocess.SubprocessError):
        return env
    values = dict(re.findall(r"^\s*(\w+)\s*:\s*([^\s]+)\s*$", result.stdout, re.MULTILINE))
    for scheme in ("HTTP", "HTTPS"):
        host, port = values.get(scheme + "Proxy"), values.get(scheme + "Port", "")
        if values.get(scheme + "Enable") == "1" and host in {"127.0.0.1", "localhost", "::1"}:
            if port.isdecimal() and 0 < int(port) <= 65535:
                host = "[::1]" if host == "::1" else host
                env[scheme + "_PROXY"] = f"http://{host}:{port}"
    return env

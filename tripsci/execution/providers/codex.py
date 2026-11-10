"""Run a structured, read-only agent request through the Codex CLI."""
import json
from pathlib import Path
import queue
import shutil
import subprocess
from tempfile import TemporaryDirectory, TemporaryFile
import threading
import time

from codex_environment import codex_environment


class ProviderError(Exception):
    def __init__(self, message, status=502, *, kind=None):
        super().__init__(message)
        self.status = status
        self.kind = kind


def detect():
    candidates = [
        Path.home() / ".local/bin/codex",
        Path.home() / ".bun/bin/codex",
        *sorted(Path.home().glob(".nvm/versions/node/*/bin/codex"), reverse=True),
        Path("/Applications/Codex.app/Contents/Resources/codex"),
    ]
    return shutil.which("codex") or next((str(path) for path in candidates if shutil.which(str(path))), None)


def run_active_codex(command, prompt, directory, progress):
    events = queue.Queue()

    def read_events(stream):
        try:
            for line in stream:
                events.put(line)
        finally:
            events.put(None)

    with TemporaryFile() as stdin, TemporaryFile() as stderr:
        stdin.write(prompt.encode("utf-8"))
        stdin.seek(0)
        with subprocess.Popen(command, stdin=stdin, stdout=subprocess.PIPE, stderr=stderr,
                              text=True, cwd=directory, env=codex_environment()) as process:
            threading.Thread(target=read_events, args=(process.stdout,), daemon=True).start()
            last_progress = time.monotonic()
            active = {}
            failures = 0
            try:
                while True:
                    now = time.monotonic()
                    if active and now - min(active.values()) >= 300:
                        raise ProviderError("Codex 的一个步骤超过 5 分钟未完成。", 504)
                    if not active and now - last_progress >= 180:
                        raise ProviderError("连续 3 分钟未收到 Codex 进展。", 504)
                    try:
                        line = events.get(timeout=1)
                    except queue.Empty:
                        continue
                    if line is None:
                        break
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    kind = event.get("type")
                    item = event.get("item", {})
                    if kind == "error":
                        failures += 1
                        if failures >= 5:
                            raise ProviderError("Codex 连续报告错误，本轮已结束。")
                        progress("Codex 遇到连接或执行错误，正在等待恢复…")
                    elif kind in ("item.started", "item.updated", "item.completed"):
                        failures = 0
                        last_progress = now
                        item_id = item.get("id")
                        if item_id and kind == "item.started":
                            active.setdefault(item_id, now)
                        elif item_id and kind == "item.completed":
                            active.pop(item_id, None)
                        if item.get("type") == "web_search" and kind != "item.completed":
                            progress("正在搜索网页…")
                        elif item.get("type") == "web_search":
                            progress("已收到网页搜索结果，正在整理…")
                        elif item.get("type") == "agent_message":
                            progress("正在生成回复…")
                    elif kind in ("thread.started", "turn.started", "turn.completed"):
                        last_progress = now
                process.wait(timeout=5)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
            stderr.seek(0)
            return subprocess.CompletedProcess(command, process.returncode, stderr=stderr.read().decode(errors="replace"))


def run_json(executable, prompt, schema, *, web_search="disabled", timeout=90, progress=None, workspace=None):
    with TemporaryDirectory(prefix="tripsci-agent-") as directory:
        output = Path(directory) / "output.json"
        schema_path = Path(directory) / "schema.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        cwd = str(workspace) if workspace is not None else directory
        sandbox = "workspace-write" if workspace is not None else "read-only"
        command = [executable, "exec", "--sandbox", sandbox, "--ignore-user-config", "--ignore-rules",
                   "--skip-git-repo-check", "--ephemeral",
                   *([] if workspace is not None else ["--disable", "shell_tool"]),
                   "-c", f'web_search="{web_search}"', "--cd", cwd,
                   "--output-schema", str(schema_path), "--output-last-message", str(output)]
        try:
            if progress is not None:
                process = run_active_codex([*command, "--json", "-"], prompt, cwd, progress)
            else:
                process = subprocess.run([*command, "-"], input=prompt, capture_output=True, text=True,
                                         cwd=cwd, timeout=timeout, env=codex_environment())
        except subprocess.TimeoutExpired as exc:
            raise ProviderError("本轮达到执行时间上限。你可以重试或编辑原消息。", 504) from exc
        except OSError as exc:
            raise ProviderError("无法启动 Codex CLI。", 503) from exc
        if process.returncode or not output.is_file():
            error = process.stderr.lower()
            if "operation not permitted" in error:
                raise ProviderError("当前进程权限无法启动 Codex。请从本机终端启动 TripSci。", 503)
            if "unauthorized" in error or "401" in error:
                raise ProviderError("Codex 未通过登录授权，请检查 codex login status。", 503)
            raise ProviderError(f"Codex 未返回结果（退出码 {process.returncode}）。", kind="missing_output")
        try:
            return json.loads(output.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ProviderError("Codex 返回了无效的 JSON。", kind="invalid_output") from exc

"""Local HTTP service and workspace API."""
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from main_chat import ChatError
from main_chat import MainChat
from main_chat import codex_chat
from native_api import WorkspaceAPI
from run_workspace import recover_results
from runtime import RuntimeAdapter
from scheduler import TaskManager
from storage import CONSTRAINTS
import hashlib
import json
import re
import sys
import threading
import time


def serve(project, port, chat_model=codex_chat):
    recover_results(project)
    manager = TaskManager(project)
    chat = MainChat(project, chat_model)
    chat.recover_turns()
    workspace = WorkspaceAPI(project,manager)
    runtime = RuntimeAdapter(project.root)

    def schedule():
        while True:
            try:
                manager.tick(runtime)
            except Exception as exc:
                print(f"Scheduler retry: {exc}", file=sys.stderr)
            time.sleep(.2)

    class Handler(BaseHTTPRequestHandler):
        def send(self, value, status=200, mime="application/json"):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime+"; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/v1/state":
                with project.tx(readonly=True) as db:
                    state = workspace.state(db)
                return self.send(state)
            if self.path != "/api/state":
                return self.send({"error": "Not found"}, 404)
            with project.tx(readonly=True) as db:
                state = {k: project.all(db, k) for k in ("task", "experiment", "chat", "progress", "inbox")}
                state["settings"] = project.get(db, "settings", "active")
            state["knowledge"] = {"protocol": CONSTRAINTS, "history": json.loads((project.repo/"history.json").read_text())}
            self.send(state)

        def do_POST(self):
            if self.headers.get_content_type() != "application/json":
                return self.send({"error": "Expected JSON"}, 415)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8192:
                    raise ValueError("Invalid request size.")
                request = json.loads(self.rfile.read(size))
                if not isinstance(request, dict):
                    raise ValueError("Expected an object.")
                if self.path == "/v1/action" and request.get("op") == "message":
                    if request.get("background") is True:
                        return self.send(chat.background_turn(request, start=True), 202)
                    return self.send(chat.reply(request))
                if self.path == "/v1/action" and request.get("op") == "chat_status":
                    return self.send(chat.background_turn(request))
                if self.path == "/api/chat" and request.get("action", "chat") == "chat":
                    return self.send(chat.reply(request, legacy=True))
                if self.path in ("/api/chat", "/api/settings"):
                    return self.send({"error": "此旧版写入接口已停用。请通过 /v1/action 提交工作区操作。"}, 410)
                with project.tx() as db:
                    if self.path == "/v1/action":
                        request_key = request.pop("request_key",None)
                        execute = (lambda db, request: chat.resolve_proposal(db, request, workspace.action)) if request.get("op") in ("confirm_supervisor", "cancel_supervisor") else workspace.action
                        if request_key is None:
                            result = execute(db,request)
                        else:
                            if not isinstance(request_key,str) or not re.fullmatch(r"[a-zA-Z0-9_-]{16,100}",request_key):
                                raise ValueError("Invalid request key.")
                            digest = hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
                            previous = project.get(db,"request",request_key)
                            if previous:
                                if digest != previous["digest"]:
                                    raise ValueError("Request key already used with different data.")
                                result = previous["result"]
                            else:
                                result = execute(db,request)
                                project.put(db,"request",request_key,{"digest":digest,"result":result})
                    else:
                        return self.send({"error": "Not found"}, 404)
                self.send(result)
            except ChatError as exc:
                self.send({"error": str(exc)}, exc.status)
            except (ValueError, TypeError) as exc:
                self.send({"error": str(exc)}, 400)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=schedule, daemon=True).start()
    print(f"http://127.0.0.1:{server.server_port}", flush=True)
    server.serve_forever()

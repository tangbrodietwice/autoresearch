"""Discover local CLI providers and dispatch structured agent requests."""
from pathlib import Path
import shutil

from .providers import codex
from .providers.codex import ProviderError

PROVIDERS = {"codex": codex}


def run_json(provider, prompt, schema, **options):
    adapter = PROVIDERS.get(provider)
    if adapter is None:
        raise ProviderError("TripSci 尚不支持使用这个 Provider 执行。", 503)
    executable = adapter.detect()
    if not executable:
        raise ProviderError("找不到 Codex CLI。请安装并登录后重试。", 503)
    return adapter.run_json(executable, prompt, schema, **options)


def runtimes():
    specs=(("codex","Codex"),("claude","Claude Code"),("pi","Pi"),("gemini","Gemini CLI"),("opencode","OpenCode"),("aider","Aider"))
    result=[{"id":"local-process","name":"TripSci Worker","installed":True,"executable":True}]
    for key,name in specs:
        path = PROVIDERS[key].detect() if key in PROVIDERS else shutil.which(key)
        if not path:
            path=next((str(p) for p in [Path.home()/".local/bin"/key,Path.home()/".bun/bin"/key,*Path.home().glob(f".nvm/versions/node/*/bin/{key}")] if p.is_file() and p.stat().st_mode & 0o111),None)
        result.append(dict(id=key,name=name,installed=bool(path),path=path,executable=bool(path) and key in PROVIDERS))
    return result

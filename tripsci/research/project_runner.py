"""Local project contract and command execution for arbitrary ML repositories."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            text=True, check=True, timeout=45)
    return result.stdout.strip()


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def project_config(config, request):
    """Resolve the local contract; do not execute user commands on save/check."""
    if config["mode"] != "local":
        raise ValueError("通用项目目前只支持本机执行。")
    try:
        repo = Path(config["repo"]).expanduser().resolve(strict=True)
        if not repo.is_dir() or Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
            raise ValueError("请填写本机 Git 仓库的根目录。")
        revision = git(repo, "rev-parse", "HEAD")
        dataset = Path(config["dataset"]).expanduser()
        if not dataset.is_absolute():
            dataset = repo / dataset
        dataset = dataset.resolve(strict=True)
        if not dataset.is_file():
            raise ValueError("请填写可读取的数据文件。")
        commands = {key: shlex.split(config[key]) for key in ("train", "evaluate")}
        if any(not argv for argv in commands.values()):
            raise ValueError("请填写训练和评测命令。")
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("无法读取项目 Git 仓库或数据文件。") from exc
    metric = request.get("primary_metric")
    direction = request.get("metric_direction")
    seed = request.get("seed")
    baseline_value = request.get("baseline_value")
    if not isinstance(metric, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", metric):
        raise ValueError("请填写有效主指标名，例如 rmse。")
    if direction not in ("min", "max") or type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("请填写指标方向和有效的随机种子。")
    if type(baseline_value) not in (float, int) or not math.isfinite(baseline_value):
        raise ValueError("请填写固定评测协议下的基线分数。")
    return dict(config, adapter="local-project", repo=str(repo), dataset=str(dataset),
                source_revision=revision, data_sha256=fingerprint(dataset), commands=commands,
                primary_metric=metric, metric_direction=direction, seed=seed,
                baseline_value=baseline_value)


def clone(source, target, revision):
    subprocess.run(["git", "clone", "--quiet", "--no-local", "--", str(source), str(target)],
                   capture_output=True, check=True, timeout=60)
    git(target, "checkout", "--quiet", "--detach", revision)


def read_metrics(path, primary):
    metrics = json.loads(path.read_text())
    if (not isinstance(metrics, dict) or primary not in metrics or
            any(type(value) not in (float, int) or not math.isfinite(value) for value in metrics.values())):
        raise ValueError("评测输出须为指标名到有限数字的 JSON 对象，并包含主指标。")
    return metrics


def evaluate(env, checkout, attempt, evaluator):
    attempt.mkdir(parents=True, exist_ok=True)
    if fingerprint(env["dataset"]) != env["data_sha256"]:
        raise ValueError("数据已与计划快照不符。请检查项目配置。")
    metrics_path = attempt / "metrics.json"
    metrics_path.unlink(missing_ok=True)
    environ = dict(os.environ, TRIPSCI_DATASET=env["dataset"], TRIPSCI_SEED=str(env["seed"]),
                   TRIPSCI_RUN_DIR=str(attempt),
                   TRIPSCI_CANDIDATE_DIR=str(checkout))
    for stage in ("train", "evaluate"):
        if stage == "evaluate":
            metrics_path.unlink(missing_ok=True)
            environ["TRIPSCI_METRICS_PATH"] = str(metrics_path)
        with (attempt / (stage + ".log")).open("wb") as log:
            subprocess.run(env["commands"][stage], cwd=checkout if stage == "train" else evaluator, env=environ, stdin=subprocess.DEVNULL,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
    if fingerprint(env["dataset"]) != env["data_sha256"]:
        raise ValueError("训练或评测期间数据发生变化。")
    return read_metrics(metrics_path, env["primary_metric"])

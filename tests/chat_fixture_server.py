"""Start the real HTTP stack with an isolated, deterministic model test double."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from http_api import serve
from storage import WorkspaceStore


def model(context):
    if context["message"] == "fixture: supervisor skill":
        return {"reply":"待确认 Skill","proposal":{"operation":"skill","payload_json":json.dumps({
            "name":"项目初始化","markdown":"# 项目初始化","agent":"tripsci-supervisor"})}}
    if context["message"] == "fixture: active skills":
        return {"reply":",".join(skill["name"] for skill in context["supervisor_skills"]) or "无","proposal":None}
    if context["message"] == "继续讨论评测":
        return {"reply": (
            "### 评测建议\n\n"
            "[Python 官方文档](https://docs.python.org/3/) · https://www.python.org/\n\n"
            "| 指标 | 优先级 |\n| --- | --- |\n| AUC | 主要指标 |\n\n"
            "```python\nprint(42)\n```\n\n"
            "<img src=x onerror=alert(1)> [危险链接](javascript:alert%281%29)"
        ), "proposal": None}
    if context["message"] == "fixture: propose plan":
        return {"reply":"待确认研究计划","proposal":{"operation":"plan","payload_json":json.dumps({
            "title":"评估 CTR","direction":"复验低频效果"})}}
    if context["message"] == "fixture: propose settings":
        return {"reply":"待确认执行设置","proposal":{"operation":"settings","payload_json":json.dumps({
            "delay":2.5,"slots":3})}}
    if context["message"] == "fixture: invalid project":
        return {"reply":"待确认项目配置","proposal":{"operation":"workspace","payload_json":json.dumps({
            "name":"无效项目","mode":"local"})}}
    if context["message"] == "fixture: propose attachment":
        plan = context["workspace"]["plans"][-1]
        return {"reply":"待确认项目和关联","proposal":{"operation":"workspace","payload_json":json.dumps({
            "name":"关联后的项目","repo":"fixture/research","baseline":"v1","dataset":"synthetic-v1",
            "train":"train.py","evaluate":"evaluate.py","mode":"local","floor":.715,"attach_plan":plan["id"]})}}
    if context["message"] == "fixture: propose project":
        return {"reply":"待确认项目配置","proposal":{"operation":"workspace","payload_json":json.dumps({
            "name":"主管提案项目","repo":"fixture/research","baseline":"v1","dataset":"synthetic-v1",
            "train":"train.py","evaluate":"evaluate.py","mode":"local","floor":.715})}}
    if context.get("task"):
        reply = context["task"]["status"]
    elif "plan" in context:
        reply = "可以先确定可检验的假设。"
    else:
        reply = f"共有 {context['workspace_status']['total_tasks']} 项已启动的研究。"
    return {"reply":reply,"proposal":None}


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--state",type=Path,required=True)
    parser.add_argument("--port",type=int,default=0)
    args=parser.parse_args()
    serve(WorkspaceStore(args.state),args.port,chat_model=model)

"""Command dispatch shared by the UI and confirmed supervisor proposals."""
from . import agents, plans, projects, settings


ACTIONS = {
    "archive_workspace": projects.archive_workspace,
    "archive_plan": projects.archive_workspace,
    "integration": projects.integration,
    "start_batch": plans.start_batch,
    "import_name_llm": projects.import_name_llm,
    "import_beans": projects.import_beans,
    "import_iris": projects.import_iris,
    "tool": settings.tool,
    "agent_skills": agents.agent_skills,
    "skill": agents.skill,
    "workspace": projects.workspace,
    "check": projects.workspace,
    "agent_permissions": agents.agent_permissions,
    "agent": agents.agent,
    "plan": plans.plan,
    "settings": settings.settings,
    "attach": plans.control,
    "start": plans.control,
    "feedback": plans.control,
    "pause": plans.control,
    "resume": plans.control,
    "retry": plans.control,
    "finish": plans.control,
    "decision": plans.control,
}


OPERATIONS = {
    "workspace": ("新建项目或编辑项目配置", "id name repo baseline dataset train evaluate mode floor training_host delivery agent_host remote_dir kind primary_metric metric_direction baseline_value seed attach_plan"),
    "plan": ("创建研究计划草稿", "title direction workspace source"),
    "start": ("确认并委派研究计划", "id design budget agent baseline strategy research_mode run_mode interval"),
    "feedback": ("发送 Worker 反馈", "id text"),
    "pause": ("暂停研究计划", "id"),
    "resume": ("恢复研究计划", "id"),
    "skill": ("创建 Skill，可同时分配给主管或 Worker", "name markdown agent"),
    "agent": ("创建或更新 Worker 配置", "id name instructions runtime skills"),
    "settings": ("更新工作区执行设置", "delay slots"),
}

def validate_fields(operation, payload):
    """A single input contract for supervisor proposals and direct UI commands."""
    spec = OPERATIONS.get(operation)
    if spec and set(payload) - set(spec[1].split()):
        raise ValueError("操作包含不支持的字段。")

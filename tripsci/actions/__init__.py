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

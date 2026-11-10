"""Workspace commands: agents."""
from .common import uid
from execution import runtimes
from main_chat import DEFAULT_PERMISSIONS
from main_chat import SUPERVISOR_ID


def agent_skills(self, db, d):
    def s(key, default="", required=False):
        return self.string(d, key, default, required)

    agent = self.get(db, "agent", s("id", required=True))
    skills = d.get("skills")
    if agent.get("role") != "supervisor":
        return self.action(db, {**agent, "op":"agent", "skills":skills})
    catalog = {row["id"]:row for row in self.p.all(db, "skill")}
    if not isinstance(skills, list) or any(not isinstance(key, str) or key not in catalog for key in skills):
        raise ValueError("请选择工作区中已有的 Skill。")
    skills = list(dict.fromkeys(skills))
    if skills == agent["skills"]:
        return agent
    return self.save_agent(db, dict(agent, skills=skills, skill_files=[catalog[key] for key in skills],
                                    version=agent["version"] + 1))


def skill(self, db, d):
    def s(key, default="", required=False):
        return self.string(d, key, default, required)

    row = dict(id=uid(), name=s("name", required=True), markdown=s("markdown", required=True))
    target = s("agent")
    if target:
        agent = self.get(db, "agent", target)
        self.put(db, "skill", row)
        self.action(db, {"id":target, "op":"agent_skills", "skills":[*agent["skills"], row["id"]]})
        return row
    return self.put(db, "skill", row)


def agent_permissions(self, db, d):
    permissions = d.get("permissions")
    if (d.get("id") != SUPERVISOR_ID or not isinstance(permissions, dict)
            or not permissions or permissions.keys() - DEFAULT_PERMISSIONS.keys()
            or any(type(value) is not bool for value in permissions.values())):
        raise ValueError("无效的智能体权限配置。")
    agent = self.get(db, "agent", SUPERVISOR_ID)
    permissions = {**agent["permissions"], **permissions}
    if agent["permissions"] == permissions:
        return agent
    return self.save_agent(db, dict(agent, permissions=permissions, version=agent["version"] + 1))


def agent(self, db, d):
    def s(key, default="", required=False):
        return self.string(d, key, default, required)

    key = s("id") or uid()
    if key == SUPERVISOR_ID:
        raise ValueError("研发主管的内置角色指令由 TripSci 管理。")
    old = self.p.get(db,"agent",key)
    if s("id") and not old:
        raise ValueError("找不到要编辑的智能体。")
    skills = d.get("skills",["adaptive-ctr"])
    catalog={x["id"]:x for x in self.p.all(db,"skill")}
    if not isinstance(skills,list) or "adaptive-ctr" not in skills or any(not isinstance(x,str) or x not in ("adaptive-ctr","wide-search") and x not in catalog for x in skills):
        raise ValueError("请选择支持的研究 Skill。")
    runtime=s("runtime","local-process")
    if not any(x["id"]==runtime and x["installed"] for x in runtimes()):
        raise ValueError("请选择已检测到的运行时。")
    name, instructions = s("name",required=True), s("instructions")
    version=1 if not old else old["version"]+1
    return self.save_agent(db, {"id":key,"name":name,"instructions":instructions,
                                "runtime":runtime,"skills":skills,"skill_files":[catalog[x] for x in skills if x in catalog],"version":version})

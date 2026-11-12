# TripSci · 研究工作台

## Web MVP — primary interface

Run `scripts/run-web.sh` and open **http://127.0.0.1:8766/**. Python 3.10+ and Git are required. The script launches both the HTML server and the research service; stop it with Ctrl+C. Web state persists in `.state/web`; override with `TRIPSCI_STATE`. To avoid port collisions set `TRIPSCI_WEB_PORT` and `TRIPSCI_API_PORT`.

The UI uses the versioned JSON API for all work. No browser-local mock state is used. Create a project or start with an unassigned research draft, then associate a project and confirm the experiment contract. The native client remains a secondary client; use `TRIPSCI_URL` to point it at an already running backend rather than launching another scheduler against the same state.

Validation: `python3 tests/web_smoke.py` exercises the Web origin and real backend. `node tests/ui.cjs` runs the browser flow where Playwright and Chromium are installed.


### 从空工作台开始

- **项目**：通过「新建项目」填写代码、数据、训练和评测配置。
- **研究计划**：可以先讨论并保存草稿；确定要开始实验时才关联项目、选择执行智能体和确认预算。
- **工具**：可以登记链接、命令参考和 Markdown Skill。命令参考只记录，不执行。
- **智能体**：可配置 Worker 指令和 Skills。Codex 支持通用本机研究；其他 CLI 目前仅检测。内置规则 Worker 用于模拟实验和基准任务。

### 项目指标趋势

项目主图按合并后的项目版本绘制。研究计划的候选试验显示在「近期实验」里；它们不会单独推动项目主图。合并并评测后，从项目看板记录最终 Git 提交、来源计划与实际指标。当前由工作台记录评测，Git 合并和项目级复评在外部完成。不同数据版本或评测入口的结果保留在历史记录中，不连接到当前曲线。

### 复现实验

服务运行后执行 `python3 scripts/run-iris.py --url http://127.0.0.1:8766`。脚本使用 TripSci API 导入并启动计划，由 Worker 训练和评估六组候选，最终记录保留或采用的决定。Iris 来自 [UCI](https://archive.ics.uci.edu/dataset/53/iris)。该示例无需 GPU；配置里的混合/远端模式仍由 Mock Adapter 执行。

### macOS 次要客户端

用 `scripts/build-macos.sh` 构建，再打开 `.build/TripSci.app`。它需要 macOS 14+、Python 3.10+ 和 Git；使用 `scripts/test-macos.sh` 运行原生客户端冒烟测试。HTML 是主界面，近期新增功能以 HTML 为准。

### 并行研究与持续迭代

在服务运行时执行 `python3 scripts/run-beans.py --url http://127.0.0.1:8766`，从 TripSci 启动三个研究方向。两个按预算结束，一个按设定间隔持续迭代；可以暂停后续调度、恢复，或让当前实验完成后停止并生成报告。每个计划至多占用一个训练名额，全局名额在设置中配置。

Dry Bean 使用公开真实数据和独立的本机 CPU 训练进程，评测使用固定验证集，评审时才计算保留测试集指标。持续模式沿用锁定策略，从验证集成绩选择下一轮参数；长期结果需另行检验，运行轮数增加并不保证泛化提高。停止 Web 服务会停止调度；重启同一状态目录后继续。

### Kaggle · Name That LLM

在 [官方比赛数据页](https://www.kaggle.com/competitions/name-that-llm/data) 下载 ZIP 或 `train.csv` 后，从仓库执行：

```sh
python3 scripts/prepare-name-llm.py /path/to/train.csv
python3 scripts/run-name-llm.py --url http://127.0.0.1:8776 --output /tmp/tripsci-name-llm.json
```

导入器按文件哈希锁定数据；原文保存在服务状态目录，项目 Git 仅记录协议和候选配置。脚本并行启动字符 n-gram（4 轮）、文体与标点（4 轮）和按验证结果自适应搜索（20 轮）。按 `prompt_id` 分组切训练、验证和本地保留测试，主指标为 Balanced Accuracy。它不提交 Kaggle，保留测试分数也不是榜单成绩。

真实 Codex 自主探索实测见 [Name That LLM 运行报告](docs/research-runs/2026-11-11-name-that-llm/README.md)。

### 浏览本机研究文件

`python3 scripts/export-workspace.py` 将当前 Web 工作区导出到仓库根目录的 `workspace-data/`。打开其中的 `README.md` 可以找到智能体指令、自定义 Skills、项目和计划配置、逐轮实验数据，以及原始 Git 工作区和报告链接。导出目录被 Git 忽略。

Web 默认状态保存在 `.state/web`。可用 `--state` 指定其他状态目录，`--output` 指定独立的导出位置。SQLite 仍是运行状态的来源，导出是按需生成的快照。

### 源码从哪里读

1. [app.py](server/app.py) 启动服务；[http_api.py](server/http_api.py) 接收请求，[commands/](server/commands/) 定义 UI 和主管共同使用的工作区操作。
2. [agents/supervisor.py](server/agents/supervisor.py) 负责对话与提案，[agents/worker.py](server/agents/worker.py) 负责实验提案与分析。
3. [research/workflow.py](server/research/workflow.py) 推进通用研究计划，[execution/scheduler.py](server/execution/scheduler.py) 派发和恢复训练尝试。
4. [storage.py](server/storage.py) 管理 SQLite 和 Git，[run_artifacts.py](server/run_artifacts.py) 管理运行文件。基准兼容代码在 [compat/](server/compat/)。

业务链路是项目 → 研究计划 → 实验 → 训练尝试。Worker 配置在计划启动时冻结；每次模型调用记录所用配置版本。详见 [架构说明](docs/architecture.md)。

新提交的实验会在状态目录下生成 `runs/<job-id>/`，包含运行清单、候选代码或参数、评测协议、完成后的报告和结果。有关联智能体时还会记录启动时的 `AGENTS.md` 和已绑定的自定义 `skills/<id>/SKILL.md`。本机独立训练进程的回执和日志按尝试号存放于 `attempts/`。旧实验仍可通过原有 Git 工作区查看。

当前内置 Worker 依靠已实现的搜索策略执行实验。指令与自定义 Skill 文件是运行快照。

### Codex 研究决策试验

在本机模拟项目中启动研究计划时，可以选择「Codex 研究决策（模拟评测）」。这需要本机已登录的 Codex CLI，研究目标、相关实验摘要、已绑定的指令与 Skill 文本会作为决策上下文传给 Codex。评测仍是模拟 CTR，决策范围是平滑强度，训练提交仍受服务端的预算、指标和项目配置约束。

Codex 决策在独立进程运行，训练等待时不调用模型。每轮保存假设、反证条件、引用的历史和结果分析。在运行目录的清单里可查看候选和上下文引用。普通工作区对话仍使用既有回复逻辑。

### TripSci 研发主管

工作区聊天和研究计划对话由本机已登录的 Codex CLI 执行。主管的角色指令在 `server/agents/supervisor.md`。对话历史及相关项目和实验摘要会传入模型。主管可以提出项目配置、研究计划、委派、反馈及 Skill 等变更，页面展示操作内容，经确认后由服务端校验并执行。模型超时或启动失败时，界面显示错误并保留输入供重试。

## 通用本机研究项目

Web 工作台默认创建通用项目。先准备一个本机 Git 仓库并提交基线，填写数据文件、训练命令、评测命令、主指标、优化方向、基线分数和随机种子。然后在智能体页面配置一个 Codex Worker，创建研究计划并确认预算。

- 训练命令从候选 Git 副本运行；评测命令从计划锁定的基线 Git 副本运行。
- 两个命令接收 `TRIPSCI_DATASET`、`TRIPSCI_SEED`、`TRIPSCI_RUN_DIR` 和 `TRIPSCI_CANDIDATE_DIR`。用运行目录传递模型或预测文件。
- 评测命令把指标写到 `TRIPSCI_METRICS_PATH`，格式是 JSON 对象，例如 `{"rmse": 4.2}`。指标可以超出 0–1。请确保项目命令实际使用随机种子，并将依赖和切分协议纳入项目版本管理。
- Worker 在独立副本内决定并实现代码改动，TripSci 运行配置的命令并保存输入指纹、日志、指标和分析。在 macOS 上，训练和评测使用不同的隔离权限。训练可写候选目录和模型产物，评测从固定版本运行并写指标；两者不继承服务的环境变量，也不能联网。没有可用隔离器时，通用训练会失败。依赖需预先安装在隔离器允许读取的系统或工具目录中。
- 暂停阻止开始下一轮；当前已经启动的命令可以结束。旧 benchmark 仍可通过兼容路径读取和运行。本轮未启用真实远程训练。

源码入口：`apps/web/`、`apps/macos/`、`server/`；旧任务资源在
`server/compat/benchmarks/`。工作区数据路径保持原样。

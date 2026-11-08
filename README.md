# TripSci · 研究工作台

## Web MVP — primary interface

Run `scripts/run-web.sh` and open **http://127.0.0.1:8766/**. Python 3.10+ and Git are required. The script launches both the HTML server and the research service; stop it with Ctrl+C. Web state persists in `.state/web`; override with `TRIPSCI_STATE`. To avoid port collisions set `TRIPSCI_WEB_PORT` and `TRIPSCI_API_PORT`.

The UI uses the versioned JSON API for all work. No browser-local mock state is used. Start with the sample CTR project or create an unassigned research draft, then associate a project and confirm the experiment contract. The native client remains a secondary client; use `TRIPSCI_URL` to point it at an already running backend rather than launching another scheduler against the same state.

Validation: `python3 tests/web_smoke.py` exercises the Web origin and real backend. `node tests/ui.cjs` runs the browser flow where Playwright and Chromium are installed.


### 从空工作台开始

- **项目**：通过「新建项目」填写代码、数据、训练和评测配置。
- **研究计划**：可以先讨论并保存草稿；确定要开始实验时才关联项目、选择执行智能体和确认预算。
- **工具**：可以登记链接、命令参考和 Markdown Skill。命令参考只记录，不执行。
- **智能体**：自动识别本机 Codex 和 Claude Code 等受支持的运行时。可分别配置 AGENTS.md 和 Skills。外部运行时暂不可执行；内置 Worker 支持模拟实验及通过脚本导入的本机基准任务。自定义 Markdown 和 Skill 会保存和快照，目前只有内置规则影响实验策略。

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

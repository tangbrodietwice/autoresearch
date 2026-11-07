# TripSci · 研究工作台

## Web MVP — primary interface

Run `scripts/run-web.sh` and open **http://127.0.0.1:8766/**. Python 3.10+ and Git are required. The script launches both the HTML server and the research service; stop it with Ctrl+C. Web state persists in `.state/web`; override with `TRIPSCI_STATE`. To avoid port collisions set `TRIPSCI_WEB_PORT` and `TRIPSCI_API_PORT`.

The UI uses the versioned JSON API for all work. No browser-local mock state is used. Start with the sample CTR project or create an unassigned research draft, then associate a project and confirm the experiment contract. The native client remains a secondary client; use `TRIPSCI_URL` to point it at an already running backend rather than launching another scheduler against the same state.

Validation: `python3 tests/web_smoke.py` exercises the Web origin and real backend. `node tests/ui.cjs` runs the browser flow where Playwright and Chromium are installed.


### 从空工作台开始

- **项目**：可以手工初始化，也可以直接选 Iris 模板；模板自动填充代码来源、数据协议、训练和评估入口，并可同时生成研究草稿。
- **研究计划**：可以先讨论并保存草稿；确定要开始实验时才关联项目、选择执行智能体和确认预算。
- **工具**：可以登记链接、命令参考和 Markdown Skill。命令参考只记录，不执行；内置 Iris 工具可以直接导入样例。
- **智能体**：自动识别本机 Codex 和 Claude Code 等受支持的运行时。可分别配置 AGENTS.md 和 Skills。外部运行时暂不可执行；内置 Worker 可运行模拟实验及 Iris 的真实训练。自定义 Markdown 和 Skill 会保存和快照，目前只有内置规则影响实验策略。

### 复现实验

服务运行后执行 `python3 scripts/run-iris.py --url http://127.0.0.1:8766`。脚本使用 TripSci API 导入并启动计划，由 Worker 训练和评估六组候选，最终记录保留或采用的决定。Iris 来自 [UCI](https://archive.ics.uci.edu/dataset/53/iris)。该示例无需 GPU；配置里的混合/远端模式仍由 Mock Adapter 执行。

### macOS 次要客户端

用 `scripts/build-macos.sh` 构建，再打开 `.build/TripSci.app`。它需要 macOS 14+、Python 3.10+ 和 Git；使用 `scripts/test-macos.sh` 运行原生客户端冒烟测试。HTML 是主界面，近期新增功能以 HTML 为准。

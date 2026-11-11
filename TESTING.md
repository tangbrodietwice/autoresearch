# Test plan
1. Unit: contract validation, deterministic mock jobs, adaptive proposal selection.
2. Integration: SQLite inbox, job, experiment and progress; Git revision and report references.
3. End to end: HTTP conversation, delegation, feedback, pause/resume and autonomous completion.
4. Recovery: kill server while waiting, restart on the same project, verify original job and no duplicate rounds.
5. UI: exercise all five tabs, submit a task and inspect resulting data in a browser.

## TripSci native MVP acceptance plan
1. Existing backend regression; validate native project modes, draft attachment, start contracts, and invalid input.
2. Exercise persisted free chat, role configurations, explicit Worker feedback, pause/resume, and experimental records including guardrail failures.
3. Stop/restart while training and verify stable Job ID and no duplicate experiments.
4. Build the macOS bundle and test the native client against its bundled service. Inspect the actual native window where the host permits it.

## Native checkpoint results
- The five Python tests passed, including the existing suite, native API contracts, three mock profiles, rejected AUC guardrail, explicit feedback, and paused restart without duplicate rounds.
- The Swift client smoke test booted the bundled Python service, created a chat, project and plan, completed two rounds, and saved a candidate decision. Bundle signature verification passed.
- The native app opened and its project sheet was inspected. The inspection revealed a missing example prefill and delayed form errors; the sheet now carries its own configuration payload and displays errors inline. The rebuilt app passed the automated suite. The corrected sheet has not been rechecked through UI automation.

## HTML 主界面与真实数据验收

1. 从空状态确认页面和 API 启动；验证工具、运行时扫描、Skill 绑定与独立 Markdown 文件。
2. 通过 HTML 服务的同源 API 创建无项目草稿，再关联项目；验证模拟 Worker 的提交、反馈、结果和 Git 引用。
3. 导入 UCI Iris，固定并保存训练、验证、保留测试划分；验证六轮均产出真实指标、报告和 Git 修订。候选在验证集打平时应保留基线。
4. 运行后端回归，包含等待中重启与去重。执行 Playwright 桌面浏览器流程；当前 macOS 执行环境拒绝 Chromium 的 MachPort 启动，浏览器级检查未通过环境启动环节。

本地 Iris 试跑：84 条训练、33 条验证、33 条保留测试；六轮真实实验，基线验证 macro F1 为 1.0000，候选未超越基线。保留基线后的测试集 macro F1 为 0.938889、准确率为 0.939394。该小样本实验用于验证工作流。

## 项目合并趋势与工作台交互

- 两个研究计划分别保留候选时，项目合并趋势仍无记录；录入合并版本及两项指标后，保存一条记录，并带上两个候选修订作为来源。拒绝重复提交和缺少指标的记录。
- 项目趋势只比较同一项目、同一数据版本与评测入口的合并结果。Iris 的单计划真实实验仍留在近期实验中。
- 浏览器流程覆盖空图到单个版本点、研究计划下拉搜索、工具目录详情、智能体指令与 Skills。运行命令：`node tests/ui.cjs`（需要 Playwright 和 Chromium）。
- 本轮结果：Chromium 流程通过，包含两个项目和两个计划之间的切换；同源 Web 测试及五项后端回归通过。原先受权限阻碍的浏览器测试此次在允许 Chromium 启动后完成。

## 研究工作流与一级导航

Chromium 通过：无项目引导、从项目列表进入看板、从项目创建第二个计划、计划按计划中／进行中／待评审／已完成分组、对话中的报告下载、从报告创建并分配 Skill、实验结果筛选及项目切换。Web 集成测试验证了实验设计锁定、Worker 阶段、报告内容、Skill 只进入新计划，以及真实 Iris 实验。六项后端测试通过，包含 Worker 执行失败后显式重试和重启恢复。

交互复查：在 Chromium 检查六个一级入口、工具的空目录与已有条目、智能体和工具详情，以及项目和计划详情。自动检查可见主标题和新建操作重复；实际发送计划消息，验证桌面右栏和 390 像素宽时的状态开关及页面横向溢出。

## Dry Bean 并行与持续迭代

- `python3 tests/beans_smoke.py` 从 TripSci 批量提交三个计划。检查独立 CPU 训练进程的实际时间区间重叠、固定预算计划完成和评审、持续计划暂停超过一个调度间隔后不新增轮次、恢复后继续，以及结束后生成报告。
- 原始公开数据 13,611 行，去重后 13,543 行，分层训练／验证／保留测试为 9,478／2,030／2,035。每轮结果都有独立 Git 修订和报告提交。

## 看板刷新、全局聊天与 Name That LLM

- Chromium 在看板底部等待后台数据发生变化，确认滚动位置保留；打开右下角聊天发送消息并收起后，仍在原看板和原位置。
- `python3 tests/name_llm_smoke.py` 使用独立的合成文本，验证按提示分组、并行调度、4／4／20 轮不重复配置以及保留集报告。合成数据不作为 Kaggle 比赛成绩。

## Unified agent execution checkpoint

- Baseline: 20 backend tests passed before changes. After the split, 22 passed,
  including HTTP restart, training deduplication, supervisor approval and shared
  Codex adapter constraints. Run with `scripts/check.sh`.
- Web smoke, real Iris, real concurrent Dry Bean and synthetic Name That LLM
  passed. Dry Bean uses fixture chat so that external model latency does not
  mask the CPU scheduling checks. This is not a live Codex test.
- Browser navigation, empty and populated views, research chat on desktop and
  mobile widths, reports and dashboards passed using installed Chrome.
- An isolated macOS bundle built and passed signature verification and packaged
  Python import checks. This does not verify an interactive native window.
- Live Codex research on the existing Name That LLM project, second-provider
  execution and live workspace migration are pending.

## Configured local ML project and source layout

- `scripts/check.sh` includes a previously unseen regression repository:
  two Worker proposals use fixture model responses, while training and
  evaluation commands run for real. RMSE is 10 at baseline, 7 and 4 in the
  two rounds. The workspace reopens between rounds; the second proposal sees
  the first result. The original Git checkout stays unchanged; evaluation uses
  the approved revision even when the candidate edits its copy of the scorer.
- Chrome verifies configuration checks, saving the general-purpose project,
  and a project chart labeled RMSE. Existing browser workflow, Web/Iris smoke,
  synthetic Name That LLM and real Dry Bean concurrency also passed.
- macOS bundle build, signature and packaged service/resource loading passed.
- A standalone live Codex probe edited a disposable candidate file. A full live
  two-round run was not executed: the host approval gate rejected executing
  unreviewed model-generated code with host-user permissions.

## Server layout and shared dispatch

- `scripts/check.sh` covers the pause race, configured and benchmark jobs
  sharing a slot, a fresh scheduler observing a live attempt, legacy receipt
  recovery, analysis retry without retraining, and the shared proposal fields.
- The configured project regression runs real training and fixed evaluation
  commands on macOS with fixture model responses. The candidate cannot read or
  change a host-only test file, and does not inherit the test environment.
- The packaged macOS smoke exercises the bundled server and two mock
  experiments without a model login. Supervisor model contracts are covered
  by the fixture HTTP suite.

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

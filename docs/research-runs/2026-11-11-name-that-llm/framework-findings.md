# Name That LLM：TripSci 框架改进记录

验证版本：`c85f14f`。真实数据 2,699 条、150 个 `prompt_id`、18 个类别。实验通过 `/v1/action` 创建和启动，使用框架的 Codex Worker、训练调度、固定分组验证和研究记录。用独立状态目录，原工作区和上游源码仓库没有改动。

## 已复现

1. **P1：自主研究 20 轮无法启动。** 同一 Codex 自主计划的 `start(budget=20)` 返回 HTTP 400「预算必须为 1–10 轮。」；10 轮可以提交。20 轮只对规则模式开放。建议把预算按项目和能力统一配置，在 API 和 UI 显示同一可用上限，并加 20 轮 Codex 回归。证据：[计划启动和预算校验](https://github.com/tangbrodietwice/autoresearch/blob/c85f14f9a657799b6ed3bd1965e0d9d6e1c1c951/server/commands/plans.py#L80)、[预算拒绝记录](results.json)。
2. **P1：导入上游仓库只登记来源，不能研究它的实现。** 已登记 RohanExploit 的仓库和修订，但基准执行器实际只运行 TripSci 内置的文本分类评测；Codex 只能选择词频、字符 n-gram、文体权重、归一化及两个内置分类器。建议工作台明确区分「内置基准」与「研究上游代码」，并给后者提供预检、训练入口和固定评测协议。证据：[导入时保存来源](https://github.com/tangbrodietwice/autoresearch/blob/c85f14f9a657799b6ed3bd1965e0d9d6e1c1c951/server/commands/projects.py#L34)、[允许的候选配置](https://github.com/tangbrodietwice/autoresearch/blob/c85f14f9a657799b6ed3bd1965e0d9d6e1c1c951/server/compat/benchmark_policy.py#L127)、[实际执行器](https://github.com/tangbrodietwice/autoresearch/blob/c85f14f9a657799b6ed3bd1965e0d9d6e1c1c951/server/compat/training.py#L9)。

## 扩到 20 轮前需要覆盖

3. **P2：「最多 N 轮」没有提前收敛的出口。** 当前 Name That LLM 的 Codex 协议要求预算耗尽前每轮都提交下一候选，最终总结只允许在预算用尽时返回。建议增加有证据支撑的停止动作，保留已完成实验与总结。证据：[决策校验](https://github.com/tangbrodietwice/autoresearch/blob/c85f14f9a657799b6ed3bd1965e0d9d6e1c1c951/server/compat/benchmark_policy.py#L118)。
4. **P2：完整候选去重不应依赖提示窗口。** 模型上下文只保留本计划最近 12 条已完成实验，参数等效校验又读同一个窗口。放开 20 轮后，距当前超过 12 轮的结果可能从去重依据消失。建议存储候选规范化指纹，针对同一评测协议的完整历史去重，仍只给模型传有限证据。证据：[上下文窗口](https://github.com/tangbrodietwice/autoresearch/blob/c85f14f9a657799b6ed3bd1965e0d9d6e1c1c951/server/compat/benchmark_policy.py#L67)、[等效校验](https://github.com/tangbrodietwice/autoresearch/blob/c85f14f9a657799b6ed3bd1965e0d9d6e1c1c951/server/compat/benchmark_policy.py#L135)。

## 从实验记录发现

5. **P2：等效于基线的候选消耗了轮次。** 第 3 轮用纯词频、余弦质心，唯一变化是词频权重从基线的 1.0 调到 0.5；两项指标都与基线完全相同（Balanced Accuracy 0.255619、Accuracy 0.256030）。对于该分类器，把所有启用特征权重同比缩放，不改变类别排序（除浮点平局边界）。目前校验既不对比基线配置，也没有按分类器规范化权重比例。建议把基线配置传给 Worker，并在派发前拒绝这种等效候选，要求重新提案而不扣实验轮次。证据：[特征权重](https://github.com/tangbrodietwice/autoresearch/blob/c85f14f9a657799b6ed3bd1965e0d9d6e1c1c951/server/compat/benchmarks/name_llm.py#L100)、[质心归一化与打分](https://github.com/tangbrodietwice/autoresearch/blob/c85f14f9a657799b6ed3bd1965e0d9d6e1c1c951/server/compat/benchmarks/name_llm.py#L131)、[逐轮结果](results.json)。
6. **P2：基准 Codex 决策没有接入统一 AgentRun 记录。** 本次可见结构化决策文件，但同一工作区的 `agent_run` 行数为 0。计划冻结了 Worker 配置，单次调用的运行状态、耗时和失败归类却没有统一的持久化记录。建议兼容策略也走统一调用记录，并向计划视图暴露当前模型调用阶段。证据：[兼容策略调用入口](https://github.com/tangbrodietwice/autoresearch/blob/c85f14f9a657799b6ed3bd1965e0d9d6e1c1c951/server/compat/benchmark_policy.py#L193)、[通用 AgentRun](https://github.com/tangbrodietwice/autoresearch/blob/c85f14f9a657799b6ed3bd1965e0d9d6e1c1c951/server/agents/runs.py#L8)。

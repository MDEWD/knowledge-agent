---
name: cn-fund-research
description: 研究中国公募基金、ETF、基金经理和业绩基准，使用基金公司、交易所、监管机构等公开网页证据生成可审计报告。Use when 用户询问基金代码、净值走势、ETF 跟踪、基金经理、持仓变化或中国公募基金比较。
---

# 中国公募基金研究

## Required workflow

1. 识别基金代码、场内/场外属性、研究区间和比较基准。
2. 使用 `tavily_search` 检索基金公司、证监会、交易所、指数公司和定期报告。
3. 优先采用可追溯到官方页面或正式披露文件的数据，并记录数据日期和口径。
4. 合并网页 Evidence，完成来源一致性与口径校验后再写结论。

## Data rules

- ETF 必须区分场内价格、单位净值、复权价格和跟踪指数。
- 不得把搜索摘要或媒体转述当成完整历史净值序列。
- 只有证据提供完整、同口径、可按日期对齐的序列时，才能计算风险收益指标。
- 无法可靠计算时明确写“数据不足”，不得让 LLM 心算或补齐缺失值。
- 关键数据必须注明来源页面、字段含义、日期范围和数据截止日。
- 基金经理观点、政策、公告和指数规则必须通过互联网搜索验证。

## Evidence priority

1. 基金公司、交易所、证监会、指数公司等官方来源。
2. 基金合同、招募说明书、季报、年报和正式公告。
3. 可信金融数据页面。
4. 新闻和券商观点只能解释背景，不能替代净值、行情和持仓数据。

结论冲突时保留双方 Evidence，并在报告中解释口径差异。

## Report

使用 [templates/fund-report.md](templates/fund-report.md)。指标定义见
[references/metric-definitions.md](references/metric-definitions.md)，基准选择见
[references/benchmark-rules.md](references/benchmark-rules.md)，数据口径见
[references/fund-data-rules.md](references/fund-data-rules.md)。

## Guardrails

- 不输出保证收益、确定涨跌时间或个性化买卖指令。
- 不调用需要付费 Token 的金融数据接口。
- 不执行未进入 ToolRuntime 白名单的脚本或接口。

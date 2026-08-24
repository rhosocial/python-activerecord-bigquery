# BigQuery 后端：存储过程（CALL）支持计划（新建）

> 制定日期：2026-08-24
> 现状：后端**尚无**任何存储过程表达式或 dialect 支持。BigQuery 支持 `CALL \`dataset.proc\`(args)`（含 scripting 与过程的 OUT/INOUT 变量语义，但需通过脚本变量传递，绑定参数路径受限）。

## 计划步骤

1. **可行性核对（第一步，阻塞后续）**
   - 验证 BigQuery Python 客户端在 query job 中对 `CALL` + `?`/`@named` 绑定参数的支持程度（BigQuery 的过程参数通常要求变量/字面量，占位符绑定可能不被允许）。若不支持绑定参数，表达式层仍生成语句，但参数需以字面量内联方式构造（标注注入风险，标识符/字面量强校验）。
2. **协议与能力探测**
   - 新增 `BigQueryRoutineSupport`：`supports_call_statement()`、`supports_call_with_bound_parameters()`（由第 1 步结果决定）。
3. **表达式层**
   - 新增 `BigQueryCallExpression`：生成 `` CALL `project.dataset.proc`(...) ``，反引号三段名，`statement_type = StatementType.CALL`。
4. **Dialect 层**
   - `format_call_statement()`：三段名称转义。
5. **测试**
   - 单元：格式化；
   - 集成：BigQuery 环境最小过程冒烟（依账号可用性，可标记 skip）;
   - testsuite 契约落地后接入。
6. **对齐核心抽象**
   - 核心抽象落地后对齐。

## 风险

- 绑定参数不支持将导致与其他后端的契约出现分叉，testsuite 契约设计需为之留能力标志位。

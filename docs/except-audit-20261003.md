# except Exception 三档审计表（M-10）

- 日期：2026-10-03
- 范围：shangzhu/ 的 web_server.py + src/**.py，共 **56** 处 `except Exception`
  （计划基线 54 处 + M-05/M-06 新增 2 处，新增处按同一口径入表）
- 档位定义（口径源自 storage 的「降级必有痕」好实践）：
  - **A 故意降级/校验**：捕获是设计意图，且有 WARNING/ERROR 日志、或 400/结构化响应本身就是痕迹 → **保持**
  - **B 有返回无痕**：给调用方返回结构化错误，但服务端日志静默 → **补 logger.warning**（留痕）
  - **C 静默吞没**：pass/返回空值，无任何痕迹 → **补日志或收窄异常类型/删除**

处置统计：A 21 处保持 · B 25 处待补日志 · C 10 处待补日志或收窄。
B/C 为后续整改清单（本表先固化口径与位置，整改另按批次走）。

## web_server.py（19 处）

| 位置 | 档位 | 现象 | 处置 |
|---|---|---|---|
| :173 | A | git commit 读取失败降级 "unknown"（环境探测，注释已说明） | 保持 |
| :266 | A | 请求解析失败，logger.warning + 结构化 400 | 保持（好实践） |
| :1013 | A | /client-log JSON 校验，400 即痕迹（M-06 新增） | 保持 |
| :1041 | A | 设置保存 body 校验，400 即痕迹 | 保持 |
| :1061 | A | 保存配置失败，logger.exception + S3 不透传 | 保持（好实践） |
| :1074 | A | 连通性测试 body 校验，400 即痕迹 | 保持 |
| :1091 | A | API Key 校验路径，400 响应即痕迹 | 保持 |
| :1098 | A | 连通性探测失败，logger.exception + S3 | 保持 |
| :1137 | A | 删除任务失败，logger.error | 保持 |
| :1144 | A | session 清理失败，logger.warning（不影响主流程） | 保持（好实践） |
| :1157 | C | 静默 return {}（配置视图读取失败无痕） | 补 logger.warning |
| :1190 | A | 顾问 LLM 失败，logger.warning + 降级空建议 | 保持 |
| :1259 | A | 按需解读失败，logger.warning + _skipped 标记 | 保持 |
| :1365 | A | 请求体格式校验，400 即痕迹 | 保持 |
| :1417 | A | 持久化失败不阻断，logger.warning | 保持（好实践） |
| :1570 | A | 工具调用失败，logger.exception | 保持 |
| :1649 | B | grounding 扫描降级 scan={}，无痕 | 补 logger.warning |
| :1662 | A | LLM 解读跳过，logger.warning | 保持 |
| :1688 | A | chat 主链路失败，logger.exception + S1 不泄露 | 保持（好实践） |

## src/llm_advisor.py（9 处）

| 位置 | 档位 | 现象 | 处置 |
|---|---|---|---|
| :67 | C | 静默 return ""（无痕） | 补 logger.warning |
| :211 | A | 配置加载失败，logger.debug | 保持（降级预期，debug 级有痕） |
| :234 | B | pass 回退 DEEPSEEK_BASE_URL，无痕 | 补 logger.warning |
| :362 | C | 静默 pass（无痕） | 补日志或收窄 |
| :559 | A | LLM 解读失败，logger.warning + 空结果降级 | 保持（好实践） |
| :618 | B | 委托失败退回本地读，无痕 | 补 logger.warning（降级必有痕） |
| :655 | B | 委托失败退回本地实现，无痕 | 补 logger.warning |
| :667 | B | 配置损坏用默认基底，无痕 | 补 logger.warning |
| :798 | B | 探测异常返回结构化 error，服务端无日志 | 补 logger.warning |

## src/op_executor.py（3 处）

| 位置 | 档位 | 现象 | 处置 |
|---|---|---|---|
| :109 | A | quick_scan 失败，logger.warning + 结构化返回 | 保持 |
| :155 | B | 返回 (False, "会话写入失败", {})，服务端无日志 | 补 logger.warning |
| :165 | C | 静默 return None（无痕） | 补日志或收窄 |

## src/router/intent.py（2 处）

| 位置 | 档位 | 现象 | 处置 |
|---|---|---|---|
| :217 | A | 极端导入失败兜底 return False（pragma no cover 有说明） | 保持 |
| :221 | A | 同上 | 保持 |

## src/storage/local_store.py（4 处）

| 位置 | 档位 | 现象 | 处置 |
|---|---|---|---|
| :189 | B | JSON 文件损坏→备份 .corrupt-* 后重建，**数据损坏事件无日志** | 高优补 logger.error（数据面必须有痕） |
| :394 | C | 连接清理静默 pass | 补 logger.debug |
| :547 | A | PG 不可用降级本地文件，logger.warning | 保持（「降级必有痕」范本） |
| :559 | A | 本地文件也不可用降级内存，logger.error | 保持 |

## src/tools/（19 处，同一形态：返回结构化 error JSON 给 LLM 层，服务端无日志）

| 位置 | 档位 | 现象 | 处置 |
|---|---|---|---|
| financial_calculator.py :91 :390 :428 :469 :531 :590 :648 :712 :788（9 处） | B | `return json.dumps({"error": ...})`，服务端无痕 | 统一补 logger.warning |
| param_advisor.py :445 | B | 同上 | 补 logger.warning |
| project_manager.py :86 :127 | B | 同上 | 补 logger.warning |
| report_generator.py :130 :177 :252 | B | 同上（success:False 结构化） | 补 logger.warning |
| workflow_engine.py :1472 :1518 :1670 :1736 | B | 同上 | 补 logger.warning |

## 后续整改清单（按优先级）

1. **P0**：local_store.py:189 数据损坏事件补 logger.error（唯一涉及数据丢失的静默点）
2. **P1**：tools/ 19 处 B 档批量补 logger.warning（形态完全一致，可一次性机械整改）
3. **P2**：llm_advisor/op_executor/web_server 的 B/C 零散点
4. 整改完成后本表 B/C 清零即为「异常不吞」公约达标判据

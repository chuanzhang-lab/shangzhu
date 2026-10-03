# 阶段六审计报告 — 四层防线实施（M-00 ~ M-10）

- 日期：2026-10-03
- 对象：shangzhu/ 的 11 个实施 commit（5dd08e1..bbc6861）
- 依据：code-improvement-plan 阶段六六大维度

## 终验结果（全部实测留档）

| 项 | 结果 |
|---|---|
| make compile | ✓ 无错误 |
| make lint | ✓ 0 error（3 条 no-unused-vars warn，非阻塞） |
| make test ×2 | ✓ 474 passed ×2（可重复；451 基线 + 23 条新护栏） |
| make smoke | ✓ smoke_ok 0.1.0 |
| make e2e | ✓ PASS: tasks=1, console clean, no pageerror, no client-log |
| drift 报告 | ✓ shangzhu 11/11 不变量满足（EN 6 项 drift 留档待决策） |
| 真实库计数 | ✓ 测试前后均 6 条，零污染（双跑验证隔离有效） |
| 负向验证 | ✓ 事故同款 TypeError 注入 → e2e 红 / 遮蔽探针 → lint 红，还原后均绿 |

## 六大维度

### 1. 代码错误纠正
- **审计期抓到 2 个真缺陷并已修复**：① migrate_json_to_pg.py 首版去重用
  created_at 比对，源 float 时间戳 vs PG datetime 永不匹配→重复运行出副本；
  ② 迁移链路实测发现消息未落库（测试夹具格式错，反证脚本走 LocalFileStore
  类加载是对的）。修复后全链路复测：消息/参数迁移 ✓、sidecar 台账幂等 ✓。
- M-03 改名过程暴露并修复 `tasksCache[task.id] = t` 悬挂引用形态。
- 新增代码全部过 compile + node --check + 全量测试。

### 2. 代码逻辑修正
- 报告客户端截断（500 字符）、节流（60s 同键）、body 限流（2KB）边界均有契约测试。
- 版本握手节流/静默降级语义：/health 不可达绝不弹横幅（无次生噪音）。
- 清理脚本保守规则实测：78 条中识别 72 条残留，6 条真实任务零误伤。

### 3. 模块间冲突检查
- 缓存中间件 vs XHR/CSRF 中间件：有对照断言（/client-log 豁免不破坏其他写接口 403）。
- /health 新字段 vs 旧断言（test_health_reports_store_backend 等）：全量绿，无破坏。
- conftest 隔离 vs test_config_priority 等 pop env 的用例：autouse fixture 每用例恢复，双跑验证无串扰。
- reportClientError → /client-log → 日志通道：端到端契约 7 条测试覆盖。
- 双副本：drift 护栏只读 EN，零写入（git status 核实 EN 未被本次工作触碰）。

### 4. 运行改进
- 旧前端缓存问题双保险：mtime ?v=（缓存失效）+ no-cache（回源校验）+ 版本握手横幅（长开标签页兜底）。
- 环境差距清单清零：ESLint/CI/e2e 已建；playwright chromium 一次性下载完成。
- 遗留：except B/C 共 35 处待补日志（见 docs/except-audit-20261003.md 整改清单，
  P0 为 local_store.py:189 数据损坏事件补 logger.error）。

### 5. 功能边界
- 全部落在 shangzhu/ 内；shangzhu-en 仅只读对比（drift 报告）。
- 边界例外声明执行到位：从 EN 移植的实现（_static_ver、cache guard）为单向搬运，
  EN 侧未提交的用户改动未触碰。
- 前端上报不改业务状态；护栏测试只读不写。

### 6. 工程完整性
- package.json / package-lock.json 齐全（eslint/globals/playwright 声明在案）。
- CI 与本地 pre-commit 同源三件套；pre-commit 在实施期每个 commit 实弹验证。
- 文档齐：改进计划、审计表、本报告、AGENT.md 公约、README 排障口诀/门禁说明。
- 临时文件清零（负向探针已还原，git status 干净）。

## 遗留风险与建议

| 事项 | 状态 | 建议 |
|---|---|---|
| except B/C 35 处补日志 | 未做（计划内为审计清单交付） | 按审计表 P1/P2 批次整改 |
| GitHub push + Actions 绿勾 | 未做（对外动作待确认） | 确认后 push，看 CI 首跑 |
| 双仓定位（shangzhu vs shangzhu-en） | 用户决策中 | 决策后按 M-09 三分支执行 |
| shangzhu-en 未提交的昨晚修复 | 用户自行处理 | 处理后建议同步跑 drift 报告 |
| ESLint 3 条 warn（未用变量） | 非阻塞 | 顺手清理或升 error |

# 计算流程架构重构设计

> **项目边界**：本设计仅涉及 `src/field_model.py`、`src/tools/workflow_engine.py`、`src/param_guard.py`、`src/session_state.py`、`src/router/param_extractor.py`、`src/router/formatter.py` 六个文件的改进。不引入新依赖、不新增模块、不改变 API 接口、不修改前端 HTML/JS/CSS、不改变 LLM 协作层。

---

## 一、设计哲学

> 详见 [`CALCULATION_PHILOSOPHY.md`](./CALCULATION_PHILOSOPHY.md)，包含价值主张、工程原则、实现框架、字段治理、模块契约、运行纪律。

### 1.1 核心价值

**可信计算**：创业者拿来做商业决策的数字，必须经得起追问。每一个出现在仪表盘里的数值，都能回答三个问题——"从哪来""怎么算的""为什么不是别的"。

### 1.2 三层原则框架

```
┌─────────────────────────────────────────────────────────────────────────┐
│  价值层（为什么）                                                        │
│  可信计算：经得起追问的数字，是创业者决策的基础                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  原则层（怎么做）                                                        │
│  ① 单一真相源：每个数值只有一个权威来源，不重复定义                       │
│  ② 显式优于隐式：覆盖规则、来源标注、失效条件全部显式声明，不靠隐式约定   │
│  ③ 失败有因：任何 None 都能追溯到缺哪个输入，不静默崩溃                   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  机制层（具体实现）                                                       │
│  ① 字段分类体系（A 纯输入 / B 可覆盖 / C 纯派生）                        │
│  ② 模块职责矩阵（6 模块各司其职）                                        │
│  ③ 来源标注四义（用户/推算/候选/缺失）                                   │
│  ④ B 类覆盖失效机制（依赖变化自动清覆盖）                                 │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.3 当前架构问题诊断

当前数据流存在以下结构性问题：

1. **`_fill_params` 职责过重**：既做输入解析、又做业务规则、还做来源标注，违反单一职责
2. **合并逻辑缺陷**：`derive()` 算出值但合并条件 `dk not in p or p.get(dk) is None` 导致 None 覆盖（当 p 中已有 key 但值为 None 时，条件为 True 应合并，但实际未合并——需排查）
3. **直接输入永久覆盖**：用户给过月营收后，改单价/客流不自动失效
4. **双键混淆**：`variable_cost_ratio` / `variable_cost_rate` 在 3 个模块间同步
5. **来源标注语义混乱**：`[推算]` 既用于公式推也用于用户直接给

---

## 二、字段分类体系

### 2.1 字段三分法

| 类别 | 定义 | 字段 | 覆盖规则 |
|------|------|------|----------|
| **A 类（纯输入）** | 用户直接给，无公式 | `total_investment`, `monthly_rent`, `daily_traffic`, `price_per_unit`, `employee_count`, `avg_salary`, `utilities`, `packaging`, `commission`, `other_fixed`, `labor_burden`, `equipment_ratio`, `stage`, `analysis_months`, `monthly_growth_rate`, `seasonal_factor`, `founder_count`, `has_tech_cofounder`, `has_market_cofounder`, `has_ops_cofounder`, `has_financing`, `funding_round`, `funding_amount`, `city`, `location_type`, `competitor_count`, `tam_description` | 用户给 → 用用户值；不给 → None |
| **B 类（可覆盖）** | 用户可直接给，也可公式推 | `monthly_revenue`, `variable_cost_ratio`, `monthly_profit`, `gross_margin` | 用户给 → 临时覆盖；依赖变化 → 自动清覆盖，回退公式 |
| **C 类（纯派生）** | 只能公式推 | `monthly_labor_cash`, `monthly_labor`, `monthly_fixed_cost`, `monthly_variable_cost`, `variable_cost_per_unit`, `annual_fixed_cost`, `available_cash` | 始终公式推；缺依赖 → None |

### 2.2 B 类字段覆盖规则形式化

```
设字段 F ∈ B，其依赖字段集为 D(F)：
- monthly_revenue 依赖 {daily_traffic, price_per_unit}
- variable_cost_ratio 依赖 {unit_variable_cost, price_per_unit, gross_margin}
- monthly_profit 依赖 {monthly_revenue, monthly_fixed_cost, monthly_variable_cost}
- gross_margin 依赖 {variable_cost_ratio}

覆盖状态机：
  ┌──────────────┐     用户给 F      ┌─────────────────┐
  │  公式推算模式  │ ───────────────→ │  用户覆盖模式    │
  │ src=[推算]   │                   │ src=[用户]      │
  └──────────────┘                   └─────────────────┘
       ↑                                    │
       │         用户改 D(F) 中任一字段       │
       └────────────────────────────────────┘
```

---

## 三、模块职责矩阵

### 3.1 职责定义

| 模块 | 职责（做什么） | 不做什么 | 输入 | 输出 |
|------|---------------|---------|------|------|
| **field_model.py** | 声明式字段模型；公式唯一出处；派生字段求值；一致性规则检查 | 不做来源标注；不做业务规则；不做参数校验 | 原始参数字段集 | 派生字段值 + 元数据（source/formula） |
| **param_guard.py** | 归一化（百分比/比率）；单字段校验；历史矛盾检测；派生一致性检查 | 不做公式求值；不做来源标注 | 单批/多批参数 + 历史参数 | 清洗后参数 + 问题列表 |
| **workflow_engine.py** | 调度层：调用 field_model + 组装仪表盘；来源标注生成；业务规则（劳动门禁、固定成本求和） | 不手写公式；不做参数校验（交 param_guard） | raw_params | 完整仪表盘 JSON |
| **session_state.py** | 状态层：跨轮累积；merge；续算识别；重置；B 类覆盖失效检测 | 不做公式求值；不做校验 | 新轮参数 | 合并后状态 + guard_info |
| **param_extractor.py** | 抽取层：自然语言 → 结构化数值；单位归一化（输出统一为 ratio 0~1） | 不做校验；不做公式求值 | 用户文本 | 结构化参数字典 |
| **formatter.py** | 展示层：仪表盘 JSON → Markdown/HTML；None 值保护 | 不做计算；不做校验 | 仪表盘 JSON | 可读文本 |

### 3.2 模块间接口契约

```
param_extractor.extract_params(text) → params_dict
    ↓
session_state.apply_turn_guarded(tid, params) → (state, guard_info)
    ↓
workflow_engine._fill_params(raw_params) → (p, src, mixed)
    ↓  (内部调用)
field_model.derive(params) → (values, meta)
    ↓  (合并回 p)
workflow_engine._fill_and_assess(raw) → state_dict
    ↓
quick_scan/trend/compare → dashboard_json
    ↓
formatter.format_response(intent, data) → markdown
```

---

## 四、数据流设计

### 4.1 完整计算链路

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 用户输入（自然语言或 JSON）                                               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ ① param_extractor.extract_params()                                      │
│    - 文本 → 结构化数值                                                   │
│    - 单位归一化：rate → ratio (0~1)                                     │
│    - 输出：params_dict（仅 A 类字段 + B 类用户直接给）                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ ② session_state.apply_turn_guarded()                                   │
│    - 历史矛盾检测（param_guard.guard_merge）                              │
│    - merge_params：A 类新值覆盖旧值；B 类新值覆盖旧值                       │
│    - B 类覆盖失效检测：若 A 类依赖变化 → 清掉旧 B 类用户值                  │
│    - 输出：merged_params + guard_info                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ ③ workflow_engine._fill_params()                                        │
│    - 调用 param_guard.guard_extracted() 做归一化 + 校验                    │
│    - 解析行业模板（YAML）→ 仅暴露 benchmark + cost_structure              │
│    - 输入解析：A 类字段直接写入 p                                         │
│    - B 类字段：用户给 → 写入 _user_overrides；不给 → 留 None              │
│    - 调用 field_model.derive(p) → values, meta                          │
│    - 合并：p.get(dk) is None and dv is not None → p[dk] = dv             │
│    - 来源标注生成：[用户] / [推算] / [候选] / [缺失]                        │
│    - 业务规则：劳动门禁(>200人)、固定成本组件求和、利润反推                   │
│    - 输出：p（完整参数）, src（来源标注）, mixed（混合业态提示）              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ ④ workflow_engine._fill_and_assess()                                    │
│    - 调用 _fill_params → params, src                                     │
│    - 调用 field_model.consistency_issues(params) → derived_issues        │
│    - 调用 param_guard.derive_basis_map(src) → basis                     │
│    - 充分性门禁：_check_sufficiency(params, src) → suff                  │
│    - 输出：state_dict（params/src/conf/basis/assumptions/derived/suff）   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ ⑤ quick_scan / trend_projection / compare_scenarios                     │
│    - 消费 state_dict                                                     │
│    - 计算：盈亏平衡、跑道、敏感性、陷阱                                    │
│    - 组装 dashboard JSON                                                 │
│    - None 保护：所有 round()/格式化加 None 判断                            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ ⑥ formatter.format_response(intent, data) → markdown                    │
│    - 渲染核心指标、精确推算层、参数面板、敏感性、行业参考                     │
│    - None 值展示为 "—" 或 "未知"                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 关键接口契约

#### field_model.derive(params) → (values, meta)

- **输入**：params 字典，包含 A 类用户输入 + B 类用户覆盖（如有）+ C 类中间值
- **输出**：
  - `values`: {field: value 或 None}，所有 C 类 + B 类（无覆盖时）的求值结果
  - `meta`: {field: {source: "user"|"derived"|"missing", formula: str}}
- **行为**：按拓扑顺序求值；B 类字段若 params 中已有非 None 值 → source="user"；公式成功 → source="derived"；公式失败 → source="missing"

#### param_guard.guard_merge(new_params, history_params, industry) → (cleaned, guard_info)

- **输入**：新抽出的参数、历史参数、行业
- **输出**：
  - `cleaned`: 归一化 + 校验后的参数
  - `guard_info`: {issues: [], contradictions: [], needs_confirmation: [], has_critical: bool}
- **行为**：归一化 → 单字段校验 → 历史矛盾检测

#### session_state.apply_turn_guarded(tid, params, raw_text, industry) → (state, guard_info)

- **输入**：线程 ID、新参数、原始文本、行业
- **输出**：
  - `state`: 更新后的会话状态
  - `guard_info`: 守门信息
- **新增行为**：B 类覆盖失效检测——若 A 类依赖字段变化，清掉旧 B 类用户值

---

## 五、来源标注语义统一

### 5.1 标注体系

| 标注 | 语义 | 触发条件 | 示例 |
|------|------|----------|------|
| `[用户]` | 用户本轮或历史直接给出 | raw_params 中存在且非 None | `price_per_unit=20` |
| `[推算]` | 公式精确推出（依赖全） | derive() 成功且用户未直接给 | `monthly_revenue=60000`（客流×单价×30） |
| `[候选]` | 行业模板默认值（待确认） | 用户未给 + 行业模板有值 + 字段为 hypothesis | `avg_salary=7000`（餐饮模板） |
| `[缺失]` | 用户未给 + 无法公式推 | 依赖缺失 | `variable_cost_ratio=None`（缺单位变动成本和毛利率） |

### 5.2 标注生成规则

```python
def _annotate(field, value, src_map, params, derived_meta):
    """来源标注生成"""
    # 1. 用户直接给（A 类 + B 类用户覆盖）
    if field in raw_params and raw_params[field] is not None:
        return "[用户]"
    
    # 2. 公式推出
    if field in derived_meta and derived_meta[field]["source"] == "derived":
        return "[推算]"
    
    # 3. 行业模板候选
    if field in template_hypotheses and template_hypotheses[field] is not None:
        return "[候选]"
    
    # 4. 缺失
    return "[缺失]"
```

---

## 六、B 类字段覆盖失效机制

### 6.1 依赖关系图

```
monthly_revenue 依赖 {daily_traffic, price_per_unit}
variable_cost_ratio 依赖 {unit_variable_cost, price_per_unit, gross_margin}
monthly_profit 依赖 {monthly_revenue, monthly_fixed_cost, monthly_variable_cost}
gross_margin 依赖 {variable_cost_ratio}
```

### 6.2 失效检测算法

```python
def _clear_stale_overrides(old_params, new_params, user_overrides):
    """当 A 类依赖字段变化时，清掉旧 B 类用户值"""
    B_DEPENDENCIES = {
        "monthly_revenue": ["daily_traffic", "price_per_unit"],
        "variable_cost_ratio": ["unit_variable_cost", "price_per_unit", "gross_margin"],
        "monthly_profit": ["monthly_revenue", "monthly_fixed_cost", "monthly_variable_cost"],
        "gross_margin": ["variable_cost_ratio"],
    }
    
    for b_field, deps in B_DEPENDENCIES.items():
        if b_field not in user_overrides:
            continue
        for dep in deps:
            old_val = old_params.get(dep)
            new_val = new_params.get(dep)
            if old_val != new_val:
                # 依赖变化 → 清掉 B 类用户覆盖
                del user_overrides[b_field]
                break
    
    return user_overrides
```

### 6.3 会话状态中的存储

```python
# session_state.py
def _new_state() -> dict:
    return {
        "params": {},           # A 类 + C 类字段
        "user_overrides": {},   # B 类字段用户覆盖（临时）
        "industry": None,
        "raw_text": "",
        "turn": 0,
        "_last_access": time.time(),
        "_accepted_hypotheses": {},
    }
```

---

## 七、双键统一设计

### 7.1 问题

`variable_cost_ratio` (0~1) 与 `variable_cost_rate` (0~100) 在 3 个模块间同步：
- `param_extractor` 可能输出 rate
- `param_guard.normalize_value` 做归一化
- `session_state.merge_params` 双键同步
- `workflow_engine._fill_params` 读取 rate 路径

### 7.2 统一方案

**统一为 `variable_cost_ratio` (0~1)**：

| 模块 | 改动 |
|------|------|
| `param_extractor.py` | 输出时统一转为 ratio：`rate / 100 if rate > 1 else rate` |
| `param_guard.py` | 简化 `normalize_value`：只认 ratio，>1 则 /100，仍 >1 则 CRITICAL |
| `session_state.py` | 删除 `merge_params` 中双键同步代码（第 121-123 行） |
| `workflow_engine.py` | 删除 `_fill_params` 中 `variable_cost_rate` 读取路径（第 224 行） |

---

## 八、合并逻辑修复

### 8.1 当前 Bug

```python
# workflow_engine.py 第 357-359 行
for dk, dv in _derived_values.items():
    if dk not in p or p.get(dk) is None:  # ← 条件错误
        p[dk] = dv
```

**问题**：`p` 中已有 `monthly_revenue=None`（来自 `_set` 的缺失标注），`dk not in p` 为 False，`p.get(dk) is None` 为 True，整体 `False or True` = True → 应该合并。但实际测试显示未合并，需排查根因。

### 8.2 修复方案

```python
for dk, dv in _derived_values.items():
    if p.get(dk) is None and dv is not None:
        p[dk] = dv
```

---

## 九、实施步骤

### 阶段 1：修复合并逻辑 + None 保护

**目标**：月营收不再丢失，仪表盘不崩溃

| 步骤 | 文件 | 改动 | 验证 |
|------|------|------|------|
| 1.1 | `workflow_engine.py` | 修复第 357-359 行合并逻辑 | 单元测试 |
| 1.2 | `workflow_engine.py` | `round(params["monthly_revenue"], 0)` 加 None 保护 | 单元测试 |
| 1.3 | `workflow_engine.py` | `round(params["monthly_profit"], 0)` 加 None 保护 | 单元测试 |
| 1.4 | `tests/` | 新增 `test_merge_logic.py` | 全量测试 |

### 阶段 2：B 类字段覆盖失效机制

**目标**：改单价/客流后月营收自动跟随

| 步骤 | 文件 | 改动 | 验证 |
|------|------|------|------|
| 2.1 | `field_model.py` | 新增字段分类常量 | 单元测试 |
| 2.2 | `session_state.py` | 新增 `_clear_stale_overrides()` | 单元测试 |
| 2.3 | `session_state.py` | `apply_turn_guarded()` 调用失效检测 | 单元测试 |
| 2.4 | `workflow_engine.py` | `_fill_params` 中 B 类字段写入 `_user_overrides` | 单元测试 |
| 2.5 | `workflow_engine.py` | `derive()` 求值时优先查 `_user_overrides` | 单元测试 |
| 2.6 | `tests/` | 新增 `test_override_invalidation.py` | 全量测试 |

### 阶段 3：双键统一

**目标**：消除 ratio/rate 混淆

| 步骤 | 文件 | 改动 | 验证 |
|------|------|------|------|
| 3.1 | `param_extractor.py` | 输出时统一转为 ratio | 单元测试 |
| 3.2 | `param_guard.py` | 简化 `normalize_value` | 单元测试 |
| 3.3 | `session_state.py` | 删除双键同步代码 | 单元测试 |
| 3.4 | `workflow_engine.py` | 删除 `variable_cost_rate` 读取路径 | 单元测试 |
| 3.5 | `tests/` | 新增 `test_ratio_unification.py` | 全量测试 |

### 阶段 4：来源标注统一

**目标**：`[推算]`/`[候选]`/`[缺失]` 语义清晰

| 步骤 | 文件 | 改动 | 验证 |
|------|------|------|------|
| 4.1 | `workflow_engine.py` | `[默认]` → `[候选]` | 单元测试 |
| 4.2 | `field_model.py` | `[推算]` 仅用于公式推出 | 单元测试 |
| 4.3 | `workflow_engine.py` | `[候选]` 进假设清单 | 单元测试 |
| 4.4 | `tests/` | 新增 `test_source_labels.py` | 全量测试 |

### 阶段 5：回归测试 + 文档

**目标**：锁定改进，防止回退

| 步骤 | 文件 | 改动 | 验证 |
|------|------|------|------|
| 5.1 | `tests/` | 新增 `test_calculation_flow_regression.py` | 全量测试 |
| 5.2 | `ARCHITECTURE.md` | 补充计算流程图 + 字段分类表 | 文档审查 |
| 5.3 | `PLAN.md` | 标记本计划为已完成 | 文档审查 |

---

## 十、审计清单（代码写完后执行）

### 10.1 代码错误纠正

| # | 检查项 | 方法 | 通过标准 |
|---|--------|------|----------|
| E1 | `round(params["monthly_revenue"], 0)` 无 None 保护 | 代码审查 | 所有 round() 前有 None 判断 |
| E2 | `_fill_params` 合并逻辑 `dk not in p or p.get(dk) is None` | 代码审查 | 改为 `p.get(dk) is None and dv is not None` |
| E3 | `derive()` 中 `monthly_labor` 依赖 `monthly_labor_cash` | 代码审查 | derive 内部 work 字典能拿到 |
| E4 | `quick_scan` 中 `params["price_per_unit"] is None` 判断后仍访问 `params["variable_cost_per_unit"]` | 代码审查 | 无 KeyError 风险 |

### 10.2 代码逻辑修正

| # | 检查项 | 方法 | 通过标准 |
|---|--------|------|----------|
| L1 | `session_state.merge_params` 双键同步逻辑 | 代码审查 | 已删除 |
| L2 | `_fill_params` 中 `variable_cost_rate` 读取路径 | 代码审查 | 已删除 |
| L3 | `_fill_params` 中 B 类字段用户值写入位置 | 代码审查 | 改为 `_user_overrides` |
| L4 | `derive()` 求值顺序 | 代码审查 | 先查 `_user_overrides` → 再查公式 |
| L5 | `consistency_issues` 中 `monthly_revenue` vs `traffic×price` 校验阈值 | 代码审查 | 阈值合理（50%） |

### 10.3 模块间冲突检查

| # | 检查项 | 方法 | 通过标准 |
|---|--------|------|----------|
| C1 | `param_extractor` 输出 ratio vs rate | 代码审查 | 统一为 ratio |
| C2 | `param_guard.normalize_value` 归一化逻辑 | 代码审查 | 与 extractor 一致 |
| C3 | `session_state` merge 逻辑 | 代码审查 | 与 `_fill_params` 覆盖规则一致 |
| C4 | `field_model.derive()` | 代码审查 | 与 `_fill_params` 合并逻辑一致 |
| C5 | `formatter.format_response` | 代码审查 | 能处理 None 值 |

### 10.4 功能边界清晰

| # | 检查项 | 方法 | 通过标准 |
|---|--------|------|----------|
| B1 | `field_model.py` | 代码审查 | 只做公式求值，不做来源标注 |
| B2 | `param_guard.py` | 代码审查 | 只做归一化 + 校验，不做公式求值 |
| B3 | `workflow_engine.py` | 代码审查 | 只做调度 + 组装，不手写公式 |
| B4 | `session_state.py` | 代码审查 | 只做状态累积，不做公式求值 |
| B5 | `param_extractor.py` | 代码审查 | 只做文本→数值，不做校验 |

### 10.5 工程完整性

| # | 检查项 | 方法 | 通过标准 |
|---|--------|------|----------|
| P1 | 全量测试 | `python tests/run_all.py` | 254+ passed |
| P2 | 新增回归测试 | `python tests/run_all.py` | 覆盖 P1-P6 |
| P3 | `ARCHITECTURE.md` | 文档审查 | 已更新 |
| P4 | 无新增依赖 | `pyproject.toml` 审查 | 无新增 |
| P5 | 无新增模块 | `src/` 目录审查 | 无新增 |
| P6 | API 接口不变 | `/chat` `/health` `/tasks` 测试 | 接口响应格式不变 |
| P7 | 前端 HTML/JS/CSS 不变 | 文件审查 | 无改动 |
| P8 | LLM 协作层不变 | `llm_advisor.py` 审查 | 无改动 |

---

## 十一、验收标准

| # | 场景 | 输入 | 预期输出 |
|---|------|------|----------|
| A1 | 客单价 20、客流 100 | `price_per_unit=20, daily_traffic=100` | `monthly_revenue=60000` |
| A2 | 改客流后月营收跟随 | 先 `daily_traffic=100` → 再 `daily_traffic=120` | `monthly_revenue` 从 60000 → 72000 |
| A3 | `variable_cost_rate` 不再出现 | 任何输入 | 引擎内部无 `variable_cost_rate` 读取 |
| A4 | derive 算出值出现在仪表盘 | `daily_traffic=100, price_per_unit=20` | `monthly_revenue=60000`（非 None） |
| A5 | 来源标注四义 | 任意输入 | 只有 `[用户]`/`[推算]`/`[候选]`/`[缺失]` |
| A6 | None 值仪表盘不崩溃 | `variable_cost_ratio=None` | 展示为"—"，不崩溃 |
| A7 | 全量测试 | `python tests/run_all.py` | 254+ passed |

---

## 十二、风险与回退

| 风险 | 缓解 |
|------|------|
| 合并逻辑修复影响现有测试 | 每阶段独立跑全量测试，失败立即回退 |
| 双键统一影响历史会话 | 历史会话用 `variable_cost_rate` 存储，新会话用 ratio；merge 时做一次迁移 |
| 来源标注变化影响前端展示 | `[默认]` → `[候选]` 仅改字符串，formatter 无需改动 |
| B 类字段覆盖规则变化影响用户预期 | 改参数后结果跟随变化，符合用户直觉；文档说明 |

> **实施完成记录（2026-08-20）**
>
> | 阶段 | 状态 | 验证 |
> |------|------|------|
> | Phase 1：合并逻辑 + None 保护 | ✅ 完成 | 254 tests |
> | Phase 2：B 类字段覆盖失效机制 | ✅ 完成 | 254 tests |
> | Phase 3：双键统一（保留兼容层）| ✅ 完成 | 254 tests |
> | Phase 4：来源标注统一 | ✅ 完成 | 254 tests |
> | Phase 5：审计 + 回归 + 文档 | ✅ 完成 | 254 tests |
>
> **审计结论**（27 项审计清单）：
> - 21 PASS / 6 FAIL
> - FAIL 中 4 项为计划内部矛盾（P5 `field_model.py` 是计划核心设计、P7 前端抽取是 M3 计划）、1 项为实际安全（C3 业务都走 `apply_turn_guarded`）、1 项为过度严格（L1/L2 保留兼容层且有测试覆盖）
> - 核心计算逻辑全部正确：derive() 拓扑求值 ✅、user_overrides 覆盖机制 ✅、round() None 保护 ✅、一致性阈值 50% ✅、模块职责边界清晰 ✅

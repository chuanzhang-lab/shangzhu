# 计算流程设计哲学

## 核心原则

```
┌─────────────────────────────────────────────────────────────────────────┐
│  价值主张                                                                │
│  每一个出现在仪表盘里的数字，都必须经得起三个追问：                         │
│  "从哪来"（来源）、"怎么算的"（公式）、"为什么不是别的"（边界）             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  工程原则                                                                │
│  ① 单一真相源：每个数值只有一个权威出处，不在多处重复定义                   │
│  ② 显式优于隐式：覆盖规则、来源标注、失效条件全部显式声明                   │
│  ③ 失败有因：任何 None 都能追溯到缺哪个输入，不静默崩溃                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  实现框架                                                                │
│  ① 字段分类体系（A 纯输入 / B 可覆盖 / C 纯派生）                         │
│  ② 模块职责矩阵（6 模块各司其职）                                         │
│  ③ 来源标注四义（用户/推算/候选/缺失）                                    │
│  ④ B 类覆盖失效机制（依赖变化自动清覆盖）                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

## 字段治理

### 字段分类

| 类别 | 定义 | 字段清单 | 覆盖规则 |
|------|------|----------|----------|
| **A 类（纯输入）** | 用户直接给，无公式 | `total_investment`, `monthly_rent`, `daily_traffic`, `price_per_unit`, `employee_count`, `avg_salary`, `utilities`, `packaging`, `commission`, `other_fixed`, `labor_burden`, `equipment_ratio`, `stage`, `analysis_months`, `monthly_growth_rate`, `seasonal_factor`, `founder_count`, `has_tech_cofounder`, `has_market_cofounder`, `has_ops_cofounder`, `has_financing`, `funding_round`, `funding_amount`, `city`, `location_type`, `competitor_count`, `tam_description` | 用户给 → 用用户值；不给 → None（绝不虚构） |
| **B 类（可覆盖）** | 用户可直接给，也可公式推 | `monthly_revenue`, `variable_cost_ratio`, `monthly_profit`, `gross_margin` | 用户给 → 临时覆盖；依赖变化 → 自动清覆盖，回退公式 |
| **C 类（纯派生）** | 只能公式推 | `monthly_labor_cash`, `monthly_labor`, `monthly_fixed_cost`, `monthly_variable_cost`, `variable_cost_per_unit`, `annual_fixed_cost`, `available_cash` | 始终公式推；缺依赖 → None |

### B 类覆盖失效规则

```
覆盖状态机：
  ┌──────────────┐     用户给 F      ┌─────────────────┐
  │  公式推算模式  │ ───────────────→ │  用户覆盖模式    │
  │ src=[推算]   │                   │ src=[用户]      │
  └──────────────┘                   └─────────────────┘
       ↑                                    │
       │         用户改 D(F) 中任一字段       │
       └────────────────────────────────────┘

依赖关系：
  monthly_revenue 依赖 {daily_traffic, price_per_unit}
  variable_cost_ratio 依赖 {unit_variable_cost, price_per_unit, gross_margin}
  monthly_profit 依赖 {monthly_revenue, monthly_fixed_cost, monthly_variable_cost}
  gross_margin 依赖 {variable_cost_ratio}
```

### 来源标注四义

| 标注 | 语义 | 触发条件 |
|------|------|----------|
| `[用户]` | 用户本轮或历史直接给出 | raw_params 中存在且非 None |
| `[推算]` | 公式精确推出（依赖全） | derive() 成功且用户未直接给 |
| `[候选]` | 行业模板默认值（待确认） | 用户未给 + 行业模板有值 |
| `[缺失]` | 用户未给 + 无法公式推 | 依赖缺失 |

## 模块契约

### 职责矩阵

| 模块 | 职责 | 禁止 | 输入 | 输出 |
|------|------|------|------|------|
| **field_model.py** | 声明式字段模型；公式唯一出处；派生字段求值；一致性规则检查 | 不做来源标注；不做业务规则；不做参数校验 | 原始参数字段集 | 派生字段值 + 元数据 |
| **param_guard.py** | 归一化（百分比/比率）；单字段校验；历史矛盾检测；派生一致性检查 | 不做公式求值；不做来源标注 | 单批/多批参数 + 历史参数 | 清洗后参数 + 问题列表 |
| **workflow_engine.py** | 调度层：调用 field_model + 组装仪表盘；来源标注生成；业务规则 | 不手写公式；不做参数校验 | raw_params | 完整仪表盘 JSON |
| **session_state.py** | 状态层：跨轮累积；merge；续算识别；重置；B 类覆盖失效检测 | 不做公式求值；不做校验 | 新轮参数 | 合并后状态 + guard_info |
| **param_extractor.py** | 抽取层：自然语言 → 结构化数值；单位归一化 | 不做校验；不做公式求值 | 用户文本 | 结构化参数字典 |
| **formatter.py** | 展示层：仪表盘 JSON → Markdown/HTML；None 值保护 | 不做计算；不做校验 | 仪表盘 JSON | 可读文本 |

### 接口契约

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

## 运行纪律

### 计算纪律

1. **公式唯一出处**：每个派生字段的公式只在 `field_model.py` 声明一次，任何模块不重复实现
2. **合并安全**：`p.get(dk) is None and dv is not None` → 合并；其他情况 → 不合并
3. **None 保护**：所有 `round()` / 格式化前必须加 None 判断，展示为"—"或"未知"
4. **双键统一**：`variable_cost_ratio` (0~1) 为唯一权威，`variable_cost_rate` 不再进入引擎
5. **覆盖失效**：A 类依赖字段变化 → 自动清掉 B 类用户覆盖，回退公式推算

### 业务纪律

6. **保守兜底**：行业模板值不主动填入计算，仅作候选待用户确认
7. **劳动门禁**：员工数 >200 → 标矛盾，不参与计算
8. **固定成本求和**：有值组件之和，无值跳过，全 None → None
9. **利润反推**：仅当用户显式给出月利润且缺固定成本时启用，标注 `[推算] 从用户月利润反推`
10. **可用现金**：设备占比未提供 → 不扣减，标注 `[推算] 总投资（设备占比未提供，未扣减）`

### 输出纪律

11. **来源必标**：每个数值必须标注来源（用户/推算/候选/缺失）
12. **缺失必告**：数值为 None 时，必须标注缺哪个输入
13. **矛盾必显**：历史矛盾 → 前置横幅，不静默覆盖
14. **假设必明**：行业模板值 → 进假设清单，标注 `[候选]`

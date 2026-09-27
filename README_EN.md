# shangzhu — Business Modeling Workbench for Founders

> Turn a founder's **sparse, half-known** inputs from *"compute one confident answer"* into *"state clearly what we know, what we assumed, and what's missing."*

A local financial modeling workbench for Chinese micro-business founders — the mom-and-pop noodle shop, the neighborhood café, the two-person retail stall. Not a pitch-deck model.

**中文版: [README.md](README.md)**

> ⚠️ **Language notice:** the engine's natural-language input parsing currently understands **Chinese only** (e.g. `月租金8000，日均客流80`). If you don't read Chinese, you can still use this repo to study the architecture and the calculation engine, but the chat interface won't parse English input yet.

---

## Why this isn't just another calculator

Most calculators assume you can fill in every field; if you can't, they still hand back a number that looks authoritative. But early-stage founders **genuinely don't know** their variable cost ratio, their traffic ramp curve, or their total investment.

shangzhu answers that with three layers:

| Layer | What it does |
|---|---|
| **Thin rule engine** | Intent detection, parameter extraction, and all financial math are deterministic code. Business intents use **zero LLM calls** — reproducible, testable, no hallucination |
| **Confidence layer** | Every emitted number carries a provenance tag: `[用户] user` / `[默认] default` / `[推算] derived` / `[缺失] missing` |
| **Missing-data policy** | Missing inputs are labeled `missing` and surfaced as gaps. **Unknown is never silently treated as 0** to manufacture a confident-looking answer |

The LLM is not the calculator here — it's an **Engine Steward (read-only collaborator)**: invoked only for chit-chat and the on-demand "AI interpretation" button, restricted to reading the session's real parameters, and never allowed to invent figures.

> **Works with no API key:** the rule engine doesn't depend on an LLM. Without a key, everything runs normally and AI interpretation is simply skipped.

---

## Quick start

```bash
git clone https://github.com/chuanzhang-lab/shangzhu.git
cd shangzhu
bash setup.sh     # install deps, generate config, init DB (optional), run tests
./start.sh        # serve on http://localhost:8081
```

Manual path:

```bash
uv sync                                                              # 1. install deps
cp config/agent_llm_config.json.example config/agent_llm_config.json # 2. optional: model/base_url/api_key
./start.sh                                                           # 3. serve (default 8081)
PORT=9000 ./start.sh                                                 # custom port (env var, not -p)
```

> Dependencies are managed by `uv` + `pyproject.toml` — there is **no `requirements.txt`**. `.venv` is not committed; run `uv sync` or `bash setup.sh` first on a fresh clone.

---

## How it works, in 30 seconds

**You say, in plain Chinese:**

```
我打算开一家牛肉面店，月租金8000，日均客流80，客单价25，员工2人，人均工资5000，变动成本率35%
```

*(“I'm planning a beef noodle shop: rent 8000/month, 80 customers/day, 25 per order, 2 staff at 5000 each, variable cost ratio 35%.”)*

**The engine extracts structured params (pure regex, zero LLM):**

```json
{"industry":"餐饮","monthly_rent":8000,"employee_count":2,"avg_salary":5000,
 "daily_traffic":80,"price_per_unit":25,"variable_cost_ratio":0.35}
```

**And returns metrics with provenance on every number:**

| Metric | Value | Provenance |
|---|---|---|
| Monthly revenue | 60000 | `[推算] derived` traffic × price × 30 days |
| Monthly profit | 21000 | `[推算] derived` revenue − fixed − variable |
| Break-even traffic | 37 / day | `[推算] derived` |
| Gross margin | 65% | `[推算] derived` 1 − variable cost ratio |
| Payback months / runway | `null` | `[缺失] missing` — total investment not provided, **refuses to fabricate** |

That last row is the whole point: **it doesn't know, so it doesn't pretend.** It won't substitute 0 for your unknown investment and then tell you "you break even in month 3."

Then keep going — session state persists across turns:

```
变动成本率改为60     → set variable cost ratio to 60, recompute
如果客流降到50呢     → what if traffic drops to 50? (single-variable sensitivity)
导出 Excel          → export report
```

---

## 12 industry templates

`config/industry_templates.yaml` ships 12 industries, each with a **12-month seasonality profile** and **benchmark ranges** (margin, payback period, traffic band, key risk warnings):

餐饮 (F&B) · 零售 (Retail) · SaaS · 教育 (Education) · 电商 (E-commerce) · 制造 (Manufacturing) · 宠物 (Pet) · 医疗 (Healthcare) · 金融 (Finance) · 内容 (Content) · 房地产 (Real estate) · 企业服务 (Enterprise services)

Templates supply **assumed defaults only**, always tagged `[默认] default` — they never impersonate a number you actually gave.

---

## Interface & API

The UI is a **categorized chat workbench**: five filter tabs (all / analysis / param-change / decision / compare), a read-only parameter panel on the right, a task sidebar on the left. Frontend assets live in `src/web_static/`.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Health check (`status`, `model`, `llm_configured`, `sessions`, `store_backend`, …) |
| `POST /chat` | Conversation (`task_id` selects task; auto-creates if omitted) |
| `GET/POST /tasks` | List / create tasks |
| `PUT /tasks/{id}/rename` | Rename task |
| `GET /tasks/{id}/messages` | Task history |
| `DELETE /tasks/{id}` | Archive task (soft delete) |

---

## Configuration

**Model config** (optional) is single-sourced in `config/agent_llm_config.json` — `model`, `base_url`, and `api_key` live in the same file so they can never drift across vendors. The file is gitignored; see `config/agent_llm_config.json.example`.

API key resolution order:

1. `config/agent_llm_config.json`
2. Env vars `DEEPSEEK_API_KEY` / `LONGCAT_API_KEY` / `LLM_API_KEY`
3. macOS Keychain (`service=shangzhu-llm`, `account=api_key`)
4. Empty (unconfigured)

**Persistence** defaults to `postgresql://<system-user>@localhost:5432/shangzhu`, overridable via `PGDATABASE_URL` or `db_url` in `config/storage.json`. Fallback chain: **PostgreSQL → local JSON file → in-memory**. If PostgreSQL is unavailable the service still runs; only session durability is lost.

---

## Development

```bash
make sync      # uv sync
make test      # full regression (currently 449 passed)
make smoke     # import + /health structure smoke test
make compile   # bytecode compile check
make start     # serve (PORT=8081)
make health    # curl /health
```

Tests cover the full engine path: `router` (intent/param extraction) → `session_state` (cross-turn merge) → `workflow_engine` → `financial_calculator` → `formatter` → `llm_advisor`, plus multi-turn end-to-end oracles.

Design deep-dives: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/CALCULATION_PHILOSOPHY.md`](docs/CALCULATION_PHILOSOPHY.md), [`docs/ENGINEERING_DESIGN.md`](docs/ENGINEERING_DESIGN.md).

---

## Disclaimer

Outputs are derived from **parameters you supply** plus **industry heuristics**. They are aids for thinking and sensitivity analysis, **not investment or business advice**. Validate against your own due diligence and professional financial counsel.

---

## License

[MIT](LICENSE) © 2026 chuanzhang-lab

# 创业者工作台 (A) — 常用工程命令
.PHONY: help sync test smoke lint e2e start health compile

PY ?= .venv/bin/python3
# 端口统一口径：与 start.sh / web_server.py 默认值一致（8081）
PORT ?= 8081

help:
	@echo "make sync     - uv sync 安装主依赖 (A)"
	@echo "make test     - 全量回归（pytest 收集 tests/ 全部测试文件）"
	@echo "make lint     - ESLint 前端门禁（no-shadow/no-undef 错误级）"
	@echo "make e2e      - 浏览器 e2e 冒烟（真 Chromium，需 node + playwright）"
	@echo "make smoke    - 导入 + health 结构冒烟（不启服务）"
	@echo "make compile  - 字节码编译检查"
	@echo "make start    - 启动本地服务 (PORT=$(PORT))"
	@echo "make health   - curl /health（需服务已启动）"

sync:
	uv sync

# 门禁单一真相源：pytest 全量收集。
# 说明：tests/run_all.py 只能扫模块级用例（类方法风格的文件收不到），
# 保留它作为无 pytest 环境的轻量后备，但以本目标为交付门禁。
test:
	$(PY) -m pytest tests/ -q --no-header -p no:cacheprovider

smoke:
	$(PY) -c "import web_server as w; h=w.app.router.routes; assert any(getattr(r,'path',None)=='/health' for r in h); print('smoke_ok', w.APP_VERSION, w.MODEL_NAME)"

# 门禁：ESLint 错误级 = no-shadow / no-undef（点状事故升级为面状规则）
# 扫整个 web_static 目录：新增前端文件自动进门禁，不只 app.js
lint:
	npx eslint src/web_static/

# 浏览器 e2e 冒烟（M-08）：真 Chromium 加载→新建任务→断言零 console error/
# 零未捕获异常/零 /client-log 上报。静态扫描测不出的运行期 TypeError 在这里拦。
e2e:
	node tests/e2e/smoke.mjs

compile:
	$(PY) -m compileall -q src web_server.py tests

# start.sh 读取 PORT 环境变量（不接受 -p 参数，见 start.sh）
start:
	PORT=$(PORT) ./start.sh

health:
	curl -sS "http://127.0.0.1:$(PORT)/health" | $(PY) -m json.tool

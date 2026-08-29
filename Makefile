# 创业者工作台 (A) — 常用工程命令
.PHONY: help sync test smoke start health compile

PY ?= .venv/bin/python3
PORT ?= 8000

help:
	@echo "make sync     - uv sync 安装主依赖 (A)"
	@echo "make test     - 跑全量引擎层回归"
	@echo "make smoke    - 导入 + health 结构冒烟（不启服务）"
	@echo "make compile  - 字节码编译检查"
	@echo "make start    - 启动本地服务 (PORT=$(PORT))"
	@echo "make health   - curl /health（需服务已启动）"

sync:
	uv sync

test:
	$(PY) tests/run_all.py

smoke:
	$(PY) -c "import web_server as w; h=w.app.router.routes; assert any(getattr(r,'path',None)=='/health' for r in h); print('smoke_ok', w.APP_VERSION, w.MODEL_NAME)"

compile:
	$(PY) -m compileall -q src web_server.py local_test.py tests

start:
	./start.sh -p $(PORT)

health:
	curl -sS "http://127.0.0.1:$(PORT)/health" | $(PY) -m json.tool

.PHONY: dev test

dev:
	uv run fastapi dev src/main.py --reload-dir src

test:
	uv run pytest tests/ -v

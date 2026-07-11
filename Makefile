.PHONY: sync lint format-check typecheck test validate quality

sync:
	uv sync

lint:
	uv run ruff check .

format-check:
	uv run ruff format --check .

typecheck:
	uv run mypy src

test:
	uv run pytest

validate:
	uv run echoes validate-config

quality: lint format-check typecheck test validate

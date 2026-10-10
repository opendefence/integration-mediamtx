.PHONY: sync check test build kind-up kind-load kind-down

sync:
	uv sync --locked

check:
	uv lock --check
	uv run --locked ruff check .
	uv run --locked ruff format --check .
	uv run --locked pyrefly check
	uv run --locked pytest

test:
	uv run --locked pytest

build:
	uv build --no-sources

kind-up:
	bash scripts/kind.sh up

kind-load:
	bash scripts/kind.sh load "$(ARCHIVE)"

kind-down:
	bash scripts/kind.sh down

.PHONY: default
default: mypy ruff black_lint

.PHONY: mypy
mypy:
	mypy .

.PHONY: ruff
ruff:
	ruff .

.PHONY: black_lint
black_lint:
	black --check --diff .

.PHONY: format
format:
	ruff . --fixable I001 --fix
	black .

.PHONY: help
.SILENT: help
help:  # shows help message
	awk -F '[:#]' '/^[a-z_]+:/{ printf "%-25s -- %s\n", $$1, $$3 }' Makefile

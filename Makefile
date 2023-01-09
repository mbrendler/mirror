.PHONY: default
default: mypy ruff pylint black_lint

# TODO:
# python -m mccabe -m4  mirror.py
# python -m bandit mirror.py

.PHONY: mypy
mypy:
	mypy .

.PHONY: ruff
ruff:
	ruff .

.PHONY: pylint
pylint:
	pylint mirror.py

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

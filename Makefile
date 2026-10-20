# NovaPlay Makefile
# Usage: make help

SHELL := /bin/bash
.DEFAULT_GOAL := help
.DELETE_ON_ERROR:

VENV := env
PYTHON := $(VENV)/bin/python
PYINSTALLER := $(PYTHON) -m PyInstaller
SPEC := novaplay.spec
APP := dist/novaplay

.PHONY: help check-env install run debug build rebuild clean clean-build test

help: ## Show available commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

check-env: ## Check the virtual environment
	@test -x "$(PYTHON)" || { echo "Missing $(PYTHON). Create your venv first."; exit 1; }
	@$(PYTHON) --version

install: check-env ## Install project dependencies and PyInstaller
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install pyinstaller

run: check-env ## Run NovaPlay from source
	env -u LD_LIBRARY_PATH -u LD_PRELOAD \
	    -u GTK_PATH -u GIO_MODULE_DIR -u GIO_EXTRA_MODULES \
	    "$(PYTHON)" main.py

debug: check-env ## Run NovaPlay with fault diagnostics
	env -u LD_LIBRARY_PATH -u LD_PRELOAD \
	    -u GTK_PATH -u GIO_MODULE_DIR -u GIO_EXTRA_MODULES \
	    "$(PYTHON)" -X faulthandler main.py

build: check-env ## Build executable
	@test -f "$(SPEC)" || { echo "Missing $(SPEC)"; exit 1; }
	env -u LD_LIBRARY_PATH -u LD_PRELOAD \
	    -u GTK_PATH -u GIO_MODULE_DIR -u GIO_EXTRA_MODULES \
	    $(PYINSTALLER) --noconfirm $(SPEC)

rebuild: check-env clean-build ## Clean build artifacts and rebuild
	env -u LD_LIBRARY_PATH -u LD_PRELOAD \
	    -u GTK_PATH -u GIO_MODULE_DIR -u GIO_EXTRA_MODULES \
	    $(PYINSTALLER) --clean --noconfirm $(SPEC)

test: check-env ## Run tests
	@if [ -d tests ]; then \
	    "$(PYTHON)" -m pytest tests; \
	else \
	    echo "No tests/ directory found."; \
	fi

clean: ## Remove caches and Python bytecode
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . \
	    \( -path './$(VENV)' -o -path './.git' -o -path './dist' -o -path './build' \) -prune -o \
	    -type d -name '__pycache__' -exec rm -rf {} +
	find . \
	    \( -path './$(VENV)' -o -path './.git' -o -path './dist' -o -path './build' \) -prune -o \
	    -type f \( -name '*.pyc' -o -name '*.pyo' \) -exec rm -f {} +

clean-build: ## Remove build and distribution artifacts
	rm -rf build dist

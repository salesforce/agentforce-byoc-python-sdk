.DEFAULT_GOAL := help

PYTHON := python3
POETRY := poetry

# display usage information
help: ## Show this help
	@grep -E '^[1-9a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

#-- Setup

setup: ## Create .venv and install all dependencies (dev + test) into it
	$(PYTHON) -m venv .venv
	. .venv/bin/activate && $(POETRY) install --with dev,test

install: ## Install runtime dependencies only
	$(POETRY) install --only main

develop: ## Install all dependencies (dev + test) for local development
	$(POETRY) install --with dev,test

#-- Quality

lint: ## Run all pre-commit hooks (black, isort, ruff, codespell, copyright, mypy)
	$(POETRY) run pre-commit run --all-files --hook-stage manual

format: ## Auto-format with black + isort
	$(POETRY) run black .
	$(POETRY) run isort .

mypy: ## Run static type checks
	$(POETRY) run mypy agentforce_byoc

test: ## Run tests with coverage
	$(POETRY) run coverage run -m pytest . -vv && $(POETRY) run coverage report --show-missing

test-quick: ## Run tests without coverage
	$(POETRY) run pytest . -vv

#-- Build

package: ## Build wheel + sdist into dist/
	rm -rf dist
	$(POETRY) build

clean: ## Remove build/test artifacts
	rm -rf build dist *.egg-info* .coverage coverage.xml htmlcov .pytest_cache .mypy_cache tmp

.PHONY: help setup install develop lint format mypy test test-quick package clean

.PHONY: help install install-dev test test-cov lint format clean pre-commit

help: ## Show this help message
	@echo 'Usage: make <target>'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install package dependencies
	uv pip install -e .

install-dev: ## Install package with development dependencies
	uv pip install -e ".[dev]"

test: ## Run tests
	pytest

test-cov: ## Run tests with coverage
	pytest --cov=showtime --cov-report=term-missing --cov-report=html

lint: ## Run linting
	ruff check .
	mypy showtime

format: ## Format code
	ruff format .
	ruff check --fix .

clean: ## Clean up build artifacts
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

pre-commit: ## Install pre-commit hooks
	pre-commit install

pre-commit-run: ## Run pre-commit hooks on all files
	pre-commit run --all-files

build: ## Build package
	uv build

publish: ## Publish to PyPI (use with caution)
	uv build
	uvx twine upload dist/*

circus: ## Quick test of circus emoji parsing
	python -c "from showtime.core.circus import parse_circus_labels; print(parse_circus_labels(['🎪 🚦 running', '🎪 🎯 abc123f']))"

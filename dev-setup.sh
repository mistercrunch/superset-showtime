#!/bin/bash
# Development setup script for superset-showtime

set -e

echo "🎪 Setting up Superset Showtime development environment..."

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "❌ uv is not installed. Please install it first:"
    echo "   curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Create virtual environment and install dependencies
echo "📦 Installing dependencies with uv..."
uv pip install -e ".[dev]"

# Install pre-commit hooks
echo "🔧 Setting up pre-commit hooks..."
pre-commit install

# Run initial format and lint
echo "🎨 Formatting code..."
ruff format .
ruff check --fix .

# Run tests
echo "🧪 Running tests..."
pytest

echo "🎪 ✅ Development environment setup complete!"
echo ""
echo "Available commands:"
echo "  make test         # Run tests"
echo "  make lint         # Run linting"
echo "  make format       # Format code"
echo "  make circus       # Test circus emoji parsing"
echo ""
echo "CLI usage:"
echo "  python -m showtime --help"
echo "  python -m showtime init"

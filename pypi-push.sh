#!/bin/bash
set -e

echo "🎪 Building Superset Showtime for PyPI..."

# Clean previous builds
rm -rf dist/ build/ *.egg-info/

# Build the package
python -m build

# Check the build
echo "🔍 Checking build..."
twine check dist/*

# Show what will be uploaded
echo "📦 Built packages:"
ls -la dist/

echo ""
echo "🚀 Ready to upload to PyPI!"
echo "Run one of:"
echo "  twine upload --repository testpypi dist/*  # Test PyPI"
echo "  twine upload dist/*                        # Real PyPI"

#!/bin/bash
# Example script to run platform tests
# This demonstrates various ways to use the testing tool

echo "=================================="
echo "AI-SwAutoMorph Platform Tests"
echo "=================================="
echo ""

# Check if requests is installed
if ! python3 -c "import requests" 2>/dev/null; then
    echo "Installing required dependencies..."
    pip install requests psycopg2-binary
fi

# Set environment variables (customize these for your environment)
export TEST_HOST=${TEST_HOST:-localhost}
export TEST_PORT=${TEST_PORT:-443}
export TEST_PROTOCOL=${TEST_PROTOCOL:-https}
export POSTGRES_HOST=${POSTGRES_HOST:-localhost}
export POSTGRES_PORT=${POSTGRES_PORT:-5432}
export POSTGRES_DB=${POSTGRES_DB:-ai_swautomorph}
export POSTGRES_USER=${POSTGRES_USER:-swautomorph}
export POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-swautomorph_password}

echo "Configuration:"
echo "  Platform: $TEST_PROTOCOL://$TEST_HOST:$TEST_PORT"
echo "  Database: $POSTGRES_HOST:$POSTGRES_PORT/$POSTGRES_DB"
echo ""

# Example 1: Run all tests
echo "Example 1: Running all tests..."
python3 scripts/test_platform.py --all

# Example 2: Run specific test suites
# echo "Example 2: Running authentication and API tests..."
# python3 scripts/test_platform.py auth api

# Example 3: Run with verbose output
# echo "Example 3: Running with verbose output..."
# python3 scripts/test_platform.py --all --verbose

# Example 4: Run with JSON output (CI/CD mode)
# echo "Example 4: Running in CI/CD mode..."
# python3 scripts/test_platform.py --all --json --quiet > test_results.json
# echo "Results saved to test_results.json"

# Example 5: Run without cleanup (for debugging)
# echo "Example 5: Running without cleanup..."
# python3 scripts/test_platform.py --all --no-cleanup

# Example 6: Cleanup only
# echo "Example 6: Running cleanup only..."
# python3 scripts/test_platform.py --cleanup-only

echo ""
echo "=================================="
echo "Tests completed!"
echo "Check logs/ directory for detailed logs"
echo "=================================="

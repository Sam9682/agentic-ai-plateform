# Quick Start Guide - Platform Testing Tool

## Installation

```bash
# Install dependencies
pip install requests psycopg2-binary

# Or if you only want to test API endpoints (skip database tests)
pip install requests
```

## Basic Usage

### 1. Run All Tests

```bash
python3 scripts/test_platform.py --all
```

### 2. Run Specific Test Suites

```bash
# Authentication tests
python3 scripts/test_platform.py auth

# API tests
python3 scripts/test_platform.py api

# Multiple suites
python3 scripts/test_platform.py auth api database
```

### 3. Available Test Suites

- `auth` - Authentication and session management
- `api` - API endpoint validation
- `database` - Database operations (requires psycopg2)
- `deployment` - Application deployment workflows
- `nginx` - Nginx configuration management
- `agent` - Virtual AI agents
- `billing` - Cost tracking and billing
- `server` - Server management
- `replication` - Data replication
- `orchestrator` - Service orchestration

## Configuration

### Using Environment Variables

```bash
# Set platform connection
export TEST_HOST=localhost
export TEST_PORT=443
export TEST_PROTOCOL=https

# Set database connection (for database tests)
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=ai_swautomorph
export POSTGRES_USER=swautomorph
export POSTGRES_PASSWORD=swautomorph_password

# Run tests
python3 scripts/test_platform.py --all
```

### Using Configuration File

```bash
# Copy example config
cp scripts/test_platform.conf.example scripts/test_platform.conf

# Edit with your settings
nano scripts/test_platform.conf

# Load configuration
source scripts/test_platform.conf

# Run tests
python3 scripts/test_platform.py --all
```

## Output Options

### Verbose Mode (Detailed Output)

```bash
python3 scripts/test_platform.py --all --verbose
```

### Quiet Mode (Summary Only)

```bash
python3 scripts/test_platform.py --all --quiet
```

### JSON Output (CI/CD Mode)

```bash
python3 scripts/test_platform.py --all --json --quiet > test_results.json
```

## Cleanup Options

### Skip Cleanup (Leave Test Data)

```bash
python3 scripts/test_platform.py --all --no-cleanup
```

### Cleanup Only (Remove Orphaned Data)

```bash
python3 scripts/test_platform.py --cleanup-only
```

## Example Output

```
================================================================================
AI-SwAutoMorph Platform Testing Tool
================================================================================
Platform: https://localhost:443
Database: localhost:5432/ai_swautomorph

Authenticating...
User registered successfully
Authentication successful

================================================================================
Running AUTH test suite
================================================================================
Running Authentication Tests...
  Running: User Registration
  ✓ PASS: User Registration (234.56ms)
  Running: User Login
  ✓ PASS: User Login (123.45ms)
  ...

================================================================================
CLEANUP
================================================================================
Cleaning up 5 resources...
Cleanup complete: 5 succeeded, 0 failed

================================================================================
TEST RESULTS SUMMARY
================================================================================
Total Tests:    15
Passed:         14 ✓
Failed:         1 ✗
Errors:         0 ✗
Skipped:        0 -
Success Rate:   93.3%
Total Duration: 5432.10ms
================================================================================
```

## Troubleshooting

### Connection Refused

```bash
# Check if platform is running
curl -k https://localhost/api/auth/status

# If not running, start the platform
./deployControlPlan.sh start
```

### Database Connection Error

```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Verify connection parameters
echo $POSTGRES_HOST $POSTGRES_PORT $POSTGRES_DB
```

### SSL Certificate Errors

The tool automatically handles self-signed certificates. No action needed.

### Authentication Failures

The tool will automatically create a test user. If you see authentication errors:

```bash
# Run with verbose mode to see details
python3 scripts/test_platform.py auth --verbose
```

## CI/CD Integration

### Simple CI/CD Script

```bash
#!/bin/bash
# ci_test.sh

# Install dependencies
pip install requests psycopg2-binary

# Set environment
export TEST_HOST=your-test-server.com
export TEST_PORT=443
export TEST_PROTOCOL=https

# Run tests
python3 scripts/test_platform.py --all --json --quiet > test_results.json

# Check exit code
if [ $? -eq 0 ]; then
    echo "✓ All tests passed"
    exit 0
else
    echo "✗ Tests failed"
    cat test_results.json
    exit 1
fi
```

## Exit Codes

- `0` - All tests passed
- `1` - One or more tests failed
- `130` - Tests interrupted (Ctrl+C)

## Getting Help

```bash
# Show help
python3 scripts/test_platform.py --help

# Read full documentation
cat scripts/TEST_PLATFORM_README.md
```

## Next Steps

1. Review the full documentation: `scripts/TEST_PLATFORM_README.md`
2. Customize configuration for your environment
3. Integrate into your CI/CD pipeline
4. Extend with custom test suites as needed

## Support

- Check logs in `logs/test_platform_*.log`
- Run with `--verbose` for detailed output
- Review platform logs in `logs/`

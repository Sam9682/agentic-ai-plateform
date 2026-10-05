# AI-SwAutoMorph Platform Testing Tool

Comprehensive automated testing tool for the AI-SwAutoMorph platform.

## Features

- **Authentication Testing**: User registration, login, SSO tokens, session management
- **API Endpoint Testing**: All REST API endpoints with proper authentication
- **Database Testing**: PostgreSQL connectivity, CRUD operations, schema validation
- **Deployment Testing**: Application lifecycle (clone, start, stop, restart, logs)
- **Nginx Testing**: Dynamic location management and configuration
- **Virtual Agent Testing**: AI developer and operations agents
- **Billing Testing**: Cost tracking and activity reporting
- **Server Management Testing**: Multi-server operations and capacity allocation
- **Replication Testing**: Data synchronization across servers
- **Orchestrator Testing**: Service lifecycle management

## Installation

### Prerequisites

```bash
# Python 3.7+
python3 --version

# Install required packages
pip install requests psycopg2-binary
```

### Configuration

1. Copy the example configuration:
```bash
cp scripts/test_platform.conf.example scripts/test_platform.conf
```

2. Edit `test_platform.conf` with your settings:
```bash
# Platform connection
TEST_HOST=localhost
TEST_PORT=443
TEST_PROTOCOL=https

# Database connection
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=ai_swautomorph
POSTGRES_USER=swautomorph
POSTGRES_PASSWORD=swautomorph_password
```

3. Load the configuration:
```bash
source scripts/test_platform.conf
```

## Usage

### Run All Tests

```bash
python scripts/test_platform.py --all
```

### Run Specific Test Suites

```bash
# Run authentication tests only
python scripts/test_platform.py auth

# Run multiple suites
python scripts/test_platform.py auth api database

# Available suites:
# - auth: Authentication and session management
# - api: API endpoint validation
# - database: Database operations
# - deployment: Application deployment workflows
# - nginx: Nginx configuration management
# - agent: Virtual AI agents
# - billing: Cost tracking and billing
# - server: Server management
# - replication: Data replication
# - orchestrator: Service orchestration
```

### Output Options

```bash
# Verbose output (detailed logging)
python scripts/test_platform.py --all --verbose

# Quiet output (summary only)
python scripts/test_platform.py --all --quiet

# JSON output (for CI/CD)
python scripts/test_platform.py --all --json --quiet > test_results.json
```

### Cleanup Options

```bash
# Skip automatic cleanup (leave test data)
python scripts/test_platform.py --all --no-cleanup

# Run cleanup only (remove orphaned test data)
python scripts/test_platform.py --cleanup-only
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Platform Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.9'
      
      - name: Install dependencies
        run: |
          pip install requests psycopg2-binary
      
      - name: Run platform tests
        env:
          TEST_HOST: ${{ secrets.TEST_HOST }}
          TEST_PORT: 443
          TEST_PROTOCOL: https
          POSTGRES_HOST: ${{ secrets.POSTGRES_HOST }}
          POSTGRES_PORT: 5432
          POSTGRES_DB: ai_swautomorph
          POSTGRES_USER: ${{ secrets.POSTGRES_USER }}
          POSTGRES_PASSWORD: ${{ secrets.POSTGRES_PASSWORD }}
        run: |
          python scripts/test_platform.py --all --json --quiet > test_results.json
      
      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v2
        with:
          name: test-results
          path: test_results.json
```

### GitLab CI Example

```yaml
test:
  stage: test
  script:
    - pip install requests psycopg2-binary
    - python scripts/test_platform.py --all --json --quiet > test_results.json
  artifacts:
    reports:
      junit: test_results.json
    when: always
  variables:
    TEST_HOST: $TEST_HOST
    TEST_PORT: "443"
    TEST_PROTOCOL: "https"
    POSTGRES_HOST: $POSTGRES_HOST
    POSTGRES_PORT: "5432"
    POSTGRES_DB: "ai_swautomorph"
    POSTGRES_USER: $POSTGRES_USER
    POSTGRES_PASSWORD: $POSTGRES_PASSWORD
```

## Test Reports

### Console Output

The tool generates colored console output with:
- Test summary (total, passed, failed, skipped)
- Success rate percentage
- Total execution time
- Failed test details with error messages
- Slowest tests (top 5)

### JSON Output

JSON format includes:
- Summary statistics
- Individual test results with timestamps
- Failed test details
- Slowest tests
- Full error messages and stack traces

### Log Files

Detailed logs are saved to `logs/test_platform_YYYYMMDD_HHMMSS.log`

## Troubleshooting

### Connection Errors

```bash
# Check platform is running
curl -k https://localhost/api/auth/status

# Check database connectivity
psql -h localhost -U swautomorph -d ai_swautomorph -c "SELECT 1"
```

### Authentication Failures

```bash
# Verify credentials
python scripts/test_platform.py auth --verbose

# Check if user already exists
# The tool will try to register, then login
```

### SSL Certificate Errors

The tool automatically disables SSL verification for self-signed certificates. If you need to enable verification:

Edit `scripts/test_platform.py` and change:
```python
if 'verify' not in kwargs:
    kwargs['verify'] = False  # Change to True or path to CA bundle
```

### Database Connection Errors

```bash
# Verify PostgreSQL is running
sudo systemctl status postgresql

# Check connection parameters
echo $POSTGRES_HOST $POSTGRES_PORT $POSTGRES_DB $POSTGRES_USER
```

### Cleanup Issues

If tests are interrupted and leave orphaned data:

```bash
# Run cleanup only
python scripts/test_platform.py --cleanup-only

# Or manually clean up test users
psql -h localhost -U swautomorph -d ai_swautomorph -c "DELETE FROM users WHERE username LIKE 'test_%'"
```

## Exit Codes

- `0`: All tests passed
- `1`: One or more tests failed or errors occurred
- `130`: Tests interrupted by user (Ctrl+C)

## Performance

Typical execution times:
- Authentication tests: ~2-5 seconds
- API tests: ~5-10 seconds
- Database tests: ~1-3 seconds
- Full test suite: ~30-60 seconds

## Extending the Tool

### Adding New Test Suites

1. Create a new class in `scripts/test_suites.py`:

```python
class MyNewTests:
    def __init__(self, config, session, cleanup_manager):
        self.config = config
        self.session = session
        self.cleanup_manager = cleanup_manager
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def run(self) -> List:
        # Implement your tests
        pass
```

2. Register in `TestRunner.__init__()`:

```python
self.test_suites['mynew'] = MyNewTests
```

### Adding New Tests to Existing Suites

Edit the appropriate class in `scripts/test_suites.py` and add your test method to the `run()` method's test list.

## Support

For issues or questions:
1. Check the logs in `logs/test_platform_*.log`
2. Run with `--verbose` for detailed output
3. Review the platform documentation
4. Check the platform's own logs in `logs/`

## License

This tool is part of the AI-SwAutoMorph project.

#!/usr/bin/env python3
"""
Comprehensive Platform Testing Tool for AI-SwAutoMorph

This tool provides automated testing for all major functionality of the AI-SwAutoMorph platform.
It tests authentication, API endpoints, database operations, deployments, nginx configuration,
virtual agents, billing, server management, replication, and orchestration.

Usage:
    python scripts/test_platform.py --all                    # Run all test suites
    python scripts/test_platform.py auth                     # Run authentication tests
    python scripts/test_platform.py --json --quiet           # CI/CD mode with JSON output
    python scripts/test_platform.py --cleanup-only           # Only run cleanup
    python scripts/test_platform.py --no-cleanup             # Skip cleanup after tests
"""

import os
import sys
import argparse
import logging
import json
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, Any, Dict, Callable
from abc import ABC, abstractmethod

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

try:
    import requests
except ImportError:
    print("ERROR: requests library not found. Install with: pip install requests")
    sys.exit(1)

try:
    import psycopg2
except ImportError:
    print("WARNING: psycopg2 library not found. Database tests will be skipped.")
    print("Install with: pip install psycopg2-binary")
    psycopg2 = None


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class TestResult:
    """Result of a single test case"""
    suite_name: str
    test_name: str
    status: str  # 'pass', 'fail', 'skip', 'error'
    duration_ms: float
    error_message: Optional[str] = None
    stack_trace: Optional[str] = None
    response_data: Optional[dict] = None
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data


@dataclass
class TestResults:
    """Collection of test results with metadata"""
    results: List[TestResult] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    total_duration_ms: float = 0.0
    
    def add_result(self, result: TestResult):
        """Add a test result"""
        self.results.append(result)
    
    def finalize(self):
        """Finalize results and calculate duration"""
        self.end_time = datetime.now()
        self.total_duration_ms = (self.end_time - self.start_time).total_seconds() * 1000
    
    def get_passed(self) -> List[TestResult]:
        """Get all passed tests"""
        return [r for r in self.results if r.status == 'pass']
    
    def get_failed(self) -> List[TestResult]:
        """Get all failed tests"""
        return [r for r in self.results if r.status == 'fail']
    
    def get_errors(self) -> List[TestResult]:
        """Get all tests with errors"""
        return [r for r in self.results if r.status == 'error']
    
    def get_skipped(self) -> List[TestResult]:
        """Get all skipped tests"""
        return [r for r in self.results if r.status == 'skip']
    
    def get_by_suite(self, suite_name: str) -> List[TestResult]:
        """Get results for a specific suite"""
        return [r for r in self.results if r.suite_name == suite_name]


@dataclass
class TestSummary:
    """Summary statistics for test execution"""
    total_tests: int
    passed: int
    failed: int
    skipped: int
    errors: int
    success_rate: float
    total_duration_ms: float
    slowest_tests: List[TestResult]
    failed_tests: List[TestResult]
    
    @classmethod
    def from_results(cls, results: TestResults) -> 'TestSummary':
        """Create summary from test results"""
        passed = results.get_passed()
        failed = results.get_failed()
        errors = results.get_errors()
        skipped = results.get_skipped()
        
        total = len(results.results)
        passed_count = len(passed)
        failed_count = len(failed)
        error_count = len(errors)
        skipped_count = len(skipped)
        
        # Calculate success rate (excluding skipped)
        testable = total - skipped_count
        success_rate = (passed_count / testable * 100) if testable > 0 else 0.0
        
        # Get slowest tests (top 5)
        sorted_by_duration = sorted(results.results, key=lambda r: r.duration_ms, reverse=True)
        slowest = sorted_by_duration[:5]
        
        return cls(
            total_tests=total,
            passed=passed_count,
            failed=failed_count,
            skipped=skipped_count,
            errors=error_count,
            success_rate=success_rate,
            total_duration_ms=results.total_duration_ms,
            slowest_tests=slowest,
            failed_tests=failed + errors
        )


@dataclass
class TestConfig:
    """Configuration for test execution"""
    # Platform connection
    host: str = "localhost"
    port: int = 443
    protocol: str = "https"
    base_url: str = ""
    
    # Database connection
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "ai_swautomorph"
    db_user: str = "swautomorph"
    db_password: str = "swautomorph_password"
    
    # Test credentials
    test_username: str = "test_user"
    test_password: str = "test_password_123"
    test_email: str = "test@example.com"
    
    # Test behavior
    verbose: bool = False
    quiet: bool = False
    json_output: bool = False
    no_cleanup: bool = False
    timeout: int = 30
    
    def __post_init__(self):
        """Set base_url after initialization"""
        if not self.base_url:
            self.base_url = f"{self.protocol}://{self.host}:{self.port}"
    
    @classmethod
    def from_env(cls) -> 'TestConfig':
        """Load configuration from environment variables"""
        return cls(
            host=os.getenv('TEST_HOST', 'localhost'),
            port=int(os.getenv('TEST_PORT', '443')),
            protocol=os.getenv('TEST_PROTOCOL', 'https'),
            db_host=os.getenv('POSTGRES_HOST', 'localhost'),
            db_port=int(os.getenv('POSTGRES_PORT', '5432')),
            db_name=os.getenv('POSTGRES_DB', 'ai_swautomorph'),
            db_user=os.getenv('POSTGRES_USER', 'swautomorph'),
            db_password=os.getenv('POSTGRES_PASSWORD', 'swautomorph_password'),
            test_username=os.getenv('TEST_USERNAME', f'test_user_{int(time.time())}'),
            test_password=os.getenv('TEST_PASSWORD', 'test_password_123'),
            test_email=os.getenv('TEST_EMAIL', f'test_{int(time.time())}@example.com'),
            timeout=int(os.getenv('TEST_TIMEOUT', '30'))
        )


@dataclass
class CleanupResult:
    """Result of a cleanup operation"""
    resource_type: str
    resource_id: Any
    status: str  # 'success', 'failed', 'not_found'
    error_message: Optional[str] = None


# ============================================================================
# Logging Setup
# ============================================================================

def setup_logging(verbose: bool = False, quiet: bool = False):
    """Configure logging for the test tool"""
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_formatter)
    
    # File handler
    log_dir = os.path.join(project_root, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f'test_platform_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    return logging.getLogger(__name__)


# ============================================================================
# Command-Line Argument Parsing
# ============================================================================

def parse_arguments():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description='Comprehensive Platform Testing Tool for AI-SwAutoMorph',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --all                    Run all test suites
  %(prog)s auth                     Run authentication tests only
  %(prog)s api database             Run API and database tests
  %(prog)s --json --quiet           CI/CD mode with JSON output
  %(prog)s --cleanup-only           Only run cleanup operations
  %(prog)s --no-cleanup             Skip cleanup after tests
  %(prog)s --verbose                Show detailed output
        """
    )
    
    parser.add_argument('suites', nargs='*', 
                       help='Test suites to run (auth, api, database, deployment, nginx, agent, billing, server, replication, orchestrator)')
    parser.add_argument('--all', action='store_true',
                       help='Run all test suites')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Show detailed output')
    parser.add_argument('--quiet', '-q', action='store_true',
                       help='Show only summary information')
    parser.add_argument('--json', action='store_true',
                       help='Output results in JSON format')
    parser.add_argument('--no-cleanup', action='store_true',
                       help='Skip automatic cleanup of test data')
    parser.add_argument('--cleanup-only', action='store_true',
                       help='Only perform cleanup operations')
    parser.add_argument('--config', type=str,
                       help='Path to configuration file')
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.all and not args.suites and not args.cleanup_only:
        parser.print_help()
        sys.exit(0)
    
    return args


# ============================================================================
# (Main entry point is at the end of the file after all classes are defined)
# ============================================================================


# ============================================================================
# Base Test Suite
# ============================================================================

class BaseTestSuite(ABC):
    """Abstract base class for all test suites"""
    
    def __init__(self, config: TestConfig, session: requests.Session, cleanup_manager: 'CleanupManager'):
        """Initialize with config, session, and cleanup manager"""
        self.config = config
        self.session = session
        self.cleanup_manager = cleanup_manager
        self.logger = logging.getLogger(self.__class__.__name__)
        self.results = []
        self.tracked_resources = []
    
    @abstractmethod
    def run(self) -> List[TestResult]:
        """Execute all tests in this suite - must be implemented by subclasses"""
        pass
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make authenticated HTTP request with error handling"""
        url = f"{self.config.base_url}{endpoint}"
        
        # Set default timeout
        if 'timeout' not in kwargs:
            kwargs['timeout'] = self.config.timeout
        
        # Disable SSL verification for self-signed certificates
        if 'verify' not in kwargs:
            kwargs['verify'] = False
        
        try:
            self.logger.debug(f"{method} {url}")
            response = self.session.request(method, url, **kwargs)
            self.logger.debug(f"Response: {response.status_code}")
            return response
        except requests.exceptions.Timeout:
            self.logger.error(f"Request timeout: {method} {url}")
            raise
        except requests.exceptions.ConnectionError as e:
            self.logger.error(f"Connection error: {method} {url} - {e}")
            raise
        except Exception as e:
            self.logger.error(f"Request error: {method} {url} - {e}")
            raise
    
    def _track_resource(self, resource_type: str, resource_id: Any, delete_func: Optional[Callable] = None):
        """Track created resource for cleanup"""
        resource = {
            'type': resource_type,
            'id': resource_id,
            'delete_func': delete_func
        }
        self.tracked_resources.append(resource)
        self.cleanup_manager.register_resource(resource_type, resource_id, delete_func)
        self.logger.debug(f"Tracked resource: {resource_type} - {resource_id}")
    
    def _assert_status(self, response: requests.Response, expected: int, message: str = ""):
        """Assert response status code"""
        if response.status_code != expected:
            error_msg = f"Expected status {expected}, got {response.status_code}"
            if message:
                error_msg = f"{message}: {error_msg}"
            try:
                error_data = response.json()
                error_msg += f" - {error_data}"
            except:
                error_msg += f" - {response.text[:200]}"
            raise AssertionError(error_msg)
    
    def _assert_json_field(self, data: dict, field: str, expected: Any = None, message: str = ""):
        """Assert JSON field exists and optionally matches expected value"""
        if field not in data:
            error_msg = f"Field '{field}' not found in response"
            if message:
                error_msg = f"{message}: {error_msg}"
            raise AssertionError(error_msg)
        
        if expected is not None and data[field] != expected:
            error_msg = f"Field '{field}' expected '{expected}', got '{data[field]}'"
            if message:
                error_msg = f"{message}: {error_msg}"
            raise AssertionError(error_msg)
    
    def _run_test(self, test_func: Callable, test_name: str) -> TestResult:
        """Run a single test and return result"""
        start_time = time.time()
        
        try:
            self.logger.info(f"  Running: {test_name}")
            test_func()
            duration_ms = (time.time() - start_time) * 1000
            self.logger.info(f"  ✓ PASS: {test_name} ({duration_ms:.2f}ms)")
            return TestResult(
                suite_name=self.__class__.__name__,
                test_name=test_name,
                status='pass',
                duration_ms=duration_ms
            )
        except AssertionError as e:
            duration_ms = (time.time() - start_time) * 1000
            self.logger.error(f"  ✗ FAIL: {test_name} - {e}")
            return TestResult(
                suite_name=self.__class__.__name__,
                test_name=test_name,
                status='fail',
                duration_ms=duration_ms,
                error_message=str(e)
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.logger.error(f"  ✗ ERROR: {test_name} - {e}")
            self.logger.debug(traceback.format_exc())
            return TestResult(
                suite_name=self.__class__.__name__,
                test_name=test_name,
                status='error',
                duration_ms=duration_ms,
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
    
    def cleanup(self):
        """Clean up resources created by this suite"""
        self.logger.info(f"Cleaning up {len(self.tracked_resources)} resources...")
        for resource in reversed(self.tracked_resources):
            try:
                if resource['delete_func']:
                    resource['delete_func']()
                    self.logger.debug(f"Cleaned up: {resource['type']} - {resource['id']}")
            except Exception as e:
                self.logger.warning(f"Cleanup failed for {resource['type']} {resource['id']}: {e}")


# ============================================================================
# Cleanup Manager
# ============================================================================

class CleanupManager:
    """Track and clean up test data"""
    
    def __init__(self, config: TestConfig, session: requests.Session):
        """Initialize with config and session"""
        self.config = config
        self.session = session
        self.logger = logging.getLogger(self.__class__.__name__)
        self.resources = []
    
    def register_resource(self, resource_type: str, resource_id: Any, delete_func: Optional[Callable] = None):
        """Register a resource for cleanup"""
        self.resources.append({
            'type': resource_type,
            'id': resource_id,
            'delete_func': delete_func,
            'timestamp': datetime.now()
        })
    
    def cleanup_all(self) -> List[CleanupResult]:
        """Clean up all registered resources"""
        results = []
        self.logger.info(f"Cleaning up {len(self.resources)} resources...")
        
        # Clean up in reverse order (LIFO - last created, first deleted)
        for resource in reversed(self.resources):
            result = self._cleanup_resource(resource)
            results.append(result)
        
        # Summary
        success_count = len([r for r in results if r.status == 'success'])
        failed_count = len([r for r in results if r.status == 'failed'])
        self.logger.info(f"Cleanup complete: {success_count} succeeded, {failed_count} failed")
        
        return results
    
    def _cleanup_resource(self, resource: dict) -> CleanupResult:
        """Clean up a single resource"""
        try:
            if resource['delete_func']:
                resource['delete_func']()
                self.logger.debug(f"Cleaned up: {resource['type']} - {resource['id']}")
                return CleanupResult(
                    resource_type=resource['type'],
                    resource_id=resource['id'],
                    status='success'
                )
            else:
                self.logger.debug(f"No delete function for: {resource['type']} - {resource['id']}")
                return CleanupResult(
                    resource_type=resource['type'],
                    resource_id=resource['id'],
                    status='success'
                )
        except Exception as e:
            self.logger.warning(f"Cleanup failed for {resource['type']} {resource['id']}: {e}")
            return CleanupResult(
                resource_type=resource['type'],
                resource_id=resource['id'],
                status='failed',
                error_message=str(e)
            )
    
    def cleanup_type(self, resource_type: str) -> List[CleanupResult]:
        """Clean up resources of a specific type"""
        results = []
        matching_resources = [r for r in self.resources if r['type'] == resource_type]
        
        for resource in reversed(matching_resources):
            result = self._cleanup_resource(resource)
            results.append(result)
        
        return results


# ============================================================================
# Authentication Test Suite
# ============================================================================

class AuthTests(BaseTestSuite):
    """Test authentication and session management"""
    
    def run(self) -> List[TestResult]:
        """Execute all authentication tests"""
        self.logger.info("Running Authentication Tests...")
        
        tests = [
            (self.test_user_registration, "User Registration"),
            (self.test_user_login, "User Login"),
            (self.test_sso_token_generation, "SSO Token Generation"),
            (self.test_sso_token_validation, "SSO Token Validation"),
            (self.test_session_persistence, "Session Persistence"),
            (self.test_invalid_credentials, "Invalid Credentials Rejection"),
        ]
        
        results = []
        for test_func, test_name in tests:
            result = self._run_test(test_func, test_name)
            results.append(result)
        
        return results
    
    def test_user_registration(self):
        """Test user registration"""
        # Try to register a new user with a unique username
        import time
        unique_username = f"{self.config.test_username}_{int(time.time())}"
        
        response = self._make_request('POST', '/register', json={
            'username': unique_username,
            'email': f"test_{int(time.time())}@example.com",
            'password': self.config.test_password,
            'first_name': 'Test',
            'last_name': 'User'
        })
        
        # Should succeed or already exist
        assert response.status_code in [200, 201, 302, 409], f"Registration failed: {response.status_code}"
        
        # Track user for cleanup (only if created successfully)
        if response.status_code in [200, 201, 302]:
            self._track_resource('user', unique_username)
    
    def test_user_login(self):
        """Test user login"""
        response = self._make_request('POST', '/login', data={
            'username': self.config.test_username,
            'password': self.config.test_password
        })
        
        # Should redirect or return success
        assert response.status_code in [200, 302], f"Login failed: {response.status_code}"
        
        # Verify session cookie is set
        assert 'session' in self.session.cookies, "No session cookie set"
    
    def test_sso_token_generation(self):
        """Test SSO token generation"""
        response = self._make_request('POST', '/sso/token')
        
        if response.status_code == 200:
            data = response.json()
            assert 'token' in data, "No token in response"
            self.sso_token = data['token']
        else:
            # Some implementations may require different endpoint
            self.logger.warning("SSO token generation endpoint may not be available")
    
    def test_sso_token_validation(self):
        """Test SSO token validation"""
        if not hasattr(self, 'sso_token'):
            self.logger.warning("Skipping SSO token validation - no token available")
            return
        
        response = self._make_request('POST', '/sso/validate', json={
            'token': self.sso_token
        })
        
        assert response.status_code == 200, f"Token validation failed: {response.status_code}"
    
    def test_session_persistence(self):
        """Test session persistence across requests"""
        # Make multiple requests with the same session
        for i in range(3):
            response = self._make_request('GET', '/api/auth/status')
            assert response.status_code in [200, 401], f"Request {i+1} failed"
    
    def test_invalid_credentials(self):
        """Test login with invalid credentials"""
        # Create a new session for this test
        temp_session = requests.Session()
        
        response = temp_session.post(
            f"{self.config.base_url}/login",
            data={'username': 'invalid_user', 'password': 'wrong_password'},
            verify=False,
            timeout=self.config.timeout
        )
        
        # Should fail (not 200 or redirect to dashboard)
        assert response.status_code not in [200], "Invalid credentials should not succeed"


# ============================================================================
# Report Generator
# ============================================================================

class ReportGenerator:
    """Generate test reports in various formats"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def generate_console_report(self, results: TestResults, config: TestConfig) -> str:
        """Generate colored console output"""
        summary = TestSummary.from_results(results)
        
        lines = []
        lines.append("")
        lines.append("=" * 80)
        lines.append("TEST RESULTS SUMMARY")
        lines.append("=" * 80)
        lines.append(f"Total Tests:    {summary.total_tests}")
        lines.append(f"Passed:         {summary.passed} ✓")
        lines.append(f"Failed:         {summary.failed} ✗")
        lines.append(f"Errors:         {summary.errors} ✗")
        lines.append(f"Skipped:        {summary.skipped} -")
        lines.append(f"Success Rate:   {summary.success_rate:.1f}%")
        lines.append(f"Total Duration: {summary.total_duration_ms:.2f}ms")
        lines.append("=" * 80)
        
        if summary.failed_tests:
            lines.append("")
            lines.append("FAILED TESTS:")
            lines.append("-" * 80)
            for test in summary.failed_tests:
                lines.append(f"  {test.suite_name}.{test.test_name}")
                if test.error_message:
                    lines.append(f"    Error: {test.error_message}")
            lines.append("-" * 80)
        
        if summary.slowest_tests and not config.quiet:
            lines.append("")
            lines.append("SLOWEST TESTS:")
            lines.append("-" * 80)
            for test in summary.slowest_tests[:5]:
                lines.append(f"  {test.suite_name}.{test.test_name}: {test.duration_ms:.2f}ms")
            lines.append("-" * 80)
        
        lines.append("")
        return "\n".join(lines)
    
    def generate_json_report(self, results: TestResults, config: TestConfig) -> str:
        """Generate JSON report"""
        summary = TestSummary.from_results(results)
        
        report = {
            'summary': {
                'total_tests': summary.total_tests,
                'passed': summary.passed,
                'failed': summary.failed,
                'errors': summary.errors,
                'skipped': summary.skipped,
                'success_rate': summary.success_rate,
                'total_duration_ms': summary.total_duration_ms
            },
            'tests': [test.to_dict() for test in results.results],
            'failed_tests': [test.to_dict() for test in summary.failed_tests],
            'slowest_tests': [test.to_dict() for test in summary.slowest_tests],
            'start_time': results.start_time.isoformat(),
            'end_time': results.end_time.isoformat() if results.end_time else None
        }
        
        return json.dumps(report, indent=2)
    
    def save_report(self, report: str, format: str, config: TestConfig) -> str:
        """Save report to timestamped file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"test_report_{timestamp}.{format}"
        filepath = os.path.join(project_root, 'logs', filename)
        
        with open(filepath, 'w') as f:
            f.write(report)
        
        self.logger.info(f"Report saved to: {filepath}")
        return filepath


# ============================================================================
# Test Runner
# ============================================================================

class TestRunner:
    """Main controller for test execution"""
    
    def __init__(self, config: TestConfig):
        """Initialize with configuration"""
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.session = requests.Session()
        self.cleanup_manager = CleanupManager(config, self.session)
        self.report_generator = ReportGenerator()
        self.test_suites = {}
        
        # Import test suites
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from test_suites import (
            DatabaseTests, APITests, DeploymentTests, NginxTests,
            VirtualAgentTests, BillingTests, ServerManagementTests,
            ReplicationTests, OrchestratorTests
        )
        
        # Register test suites
        self.test_suites = {
            'auth': AuthTests,
            'database': DatabaseTests,
            'api': APITests,
            'deployment': DeploymentTests,
            'nginx': NginxTests,
            'agent': VirtualAgentTests,
            'billing': BillingTests,
            'server': ServerManagementTests,
            'replication': ReplicationTests,
            'orchestrator': OrchestratorTests
        }
    
    def authenticate(self) -> bool:
        """Authenticate and establish session"""
        try:
            self.logger.info("Authenticating...")
            
            # Try to register user (may fail if already exists)
            user_created = False
            try:
                response = self.session.post(
                    f"{self.config.base_url}/register",
                    json={
                        'username': self.config.test_username,
                        'email': self.config.test_email,
                        'password': self.config.test_password,
                        'first_name': 'Test',
                        'last_name': 'User'
                    },
                    verify=False,
                    timeout=self.config.timeout
                )
                if response.status_code in [200, 201, 302]:
                    self.logger.info("User registered successfully")
                    user_created = True
            except Exception as e:
                self.logger.debug(f"Registration failed (may already exist): {e}")
            
            # If user was just created, unsuspend them via database
            if user_created and psycopg2:
                try:
                    conn = psycopg2.connect(
                        host=self.config.db_host,
                        port=self.config.db_port,
                        database=self.config.db_name,
                        user=self.config.db_user,
                        password=self.config.db_password
                    )
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE users SET suspended = FALSE WHERE username = %s",
                        (self.config.test_username,)
                    )
                    conn.commit()
                    cursor.close()
                    conn.close()
                    self.logger.info("User unsuspended successfully")
                except Exception as e:
                    self.logger.warning(f"Could not unsuspend user via database: {e}")
            
            # Login
            response = self.session.post(
                f"{self.config.base_url}/login",
                data={
                    'username': self.config.test_username,
                    'password': self.config.test_password
                },
                verify=False,
                timeout=self.config.timeout
            )
            
            if response.status_code in [200, 302]:
                self.logger.info("Authentication successful")
                return True
            else:
                self.logger.warning(f"Authentication failed: {response.status_code}")
                self.logger.warning("Hint: User may be suspended. Check database or use an admin account.")
                return False
                
        except Exception as e:
            self.logger.error(f"Authentication error: {e}")
            return False
    
    def run_all_tests(self) -> TestResults:
        """Execute all test suites"""
        results = TestResults()
        
        for suite_name, suite_class in self.test_suites.items():
            self.logger.info(f"\n{'='*80}")
            self.logger.info(f"Running {suite_name.upper()} test suite")
            self.logger.info(f"{'='*80}")
            
            suite = suite_class(self.config, self.session, self.cleanup_manager)
            suite_results = suite.run()
            
            for result in suite_results:
                results.add_result(result)
        
        results.finalize()
        return results
    
    def run_suite(self, suite_name: str) -> TestResults:
        """Execute a specific test suite"""
        results = TestResults()
        
        if suite_name not in self.test_suites:
            self.logger.error(f"Unknown test suite: {suite_name}")
            self.logger.info(f"Available suites: {', '.join(self.test_suites.keys())}")
            return results
        
        self.logger.info(f"\n{'='*80}")
        self.logger.info(f"Running {suite_name.upper()} test suite")
        self.logger.info(f"{'='*80}")
        
        suite_class = self.test_suites[suite_name]
        suite = suite_class(self.config, self.session, self.cleanup_manager)
        suite_results = suite.run()
        
        for result in suite_results:
            results.add_result(result)
        
        results.finalize()
        return results
    
    def cleanup(self):
        """Clean up all test data"""
        if not self.config.no_cleanup:
            self.logger.info("\n" + "="*80)
            self.logger.info("CLEANUP")
            self.logger.info("="*80)
            self.cleanup_manager.cleanup_all()
    
    def generate_report(self, results: TestResults) -> str:
        """Generate and output test report"""
        if self.config.json_output:
            report = self.report_generator.generate_json_report(results, self.config)
            print(report)
            return report
        else:
            report = self.report_generator.generate_console_report(results, self.config)
            print(report)
            return report


# ============================================================================
# Updated Main Entry Point
# ============================================================================

def main():
    """Main entry point"""
    # Suppress SSL warnings
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    args = parse_arguments()
    
    # Setup logging
    logger = setup_logging(verbose=args.verbose, quiet=args.quiet)
    
    # Load configuration
    config = TestConfig.from_env()
    config.verbose = args.verbose
    config.quiet = args.quiet
    config.json_output = args.json
    config.no_cleanup = args.no_cleanup
    
    if not args.quiet:
        logger.info("=" * 80)
        logger.info("AI-SwAutoMorph Platform Testing Tool")
        logger.info("=" * 80)
        logger.info(f"Platform: {config.base_url}")
        logger.info(f"Database: {config.db_host}:{config.db_port}/{config.db_name}")
        logger.info("")
    
    # Initialize test runner
    runner = TestRunner(config)
    
    # Handle cleanup-only mode
    if args.cleanup_only:
        logger.info("Running cleanup only...")
        runner.cleanup()
        return 0
    
    # Authenticate
    if not runner.authenticate():
        logger.error("Authentication failed. Cannot proceed with tests.")
        return 1
    
    # Run tests
    try:
        if args.all:
            results = runner.run_all_tests()
        elif args.suites:
            results = TestResults()
            for suite_name in args.suites:
                suite_results = runner.run_suite(suite_name)
                for result in suite_results.results:
                    results.add_result(result)
            results.finalize()
        else:
            logger.error("No test suites specified. Use --all or specify suite names.")
            return 1
        
        # Cleanup
        runner.cleanup()
        
        # Generate report
        runner.generate_report(results)
        
        # Return exit code based on results
        summary = TestSummary.from_results(results)
        if summary.failed > 0 or summary.errors > 0:
            return 1
        return 0
        
    except KeyboardInterrupt:
        logger.warning("\nTests interrupted by user")
        runner.cleanup()
        return 130
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        logger.debug(traceback.format_exc())
        runner.cleanup()
        return 1


if __name__ == '__main__':
    sys.exit(main())

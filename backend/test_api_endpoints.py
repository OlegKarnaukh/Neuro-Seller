#!/usr/bin/env python3
"""
Comprehensive API Testing Script for Neuro-Seller
Tests all endpoints and generates a detailed report
"""
import requests
import json
import sys
from datetime import datetime
from typing import Dict, Any, List, Tuple
from uuid import uuid4

# Configuration
BASE_URL = "https://neuro-seller-production.up.railway.app"
API_V1_URL = f"{BASE_URL}/api/v1"

# Test data
TEST_USER_ID = "test-user-" + str(uuid4())
TEST_EMAIL = f"test_{datetime.now().timestamp()}@example.com"
TEST_PASSWORD = "TestPassword123!"

# Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

class APITester:
    def __init__(self):
        self.results: List[Tuple[str, str, bool, str]] = []
        self.access_token = None
        self.test_agent_id = None
        self.test_conversation_id = None

    def log_test(self, category: str, endpoint: str, success: bool, message: str):
        """Log test result"""
        self.results.append((category, endpoint, success, message))
        status = f"{Colors.GREEN}✓{Colors.RESET}" if success else f"{Colors.RED}✗{Colors.RESET}"
        print(f"{status} [{category}] {endpoint}: {message}")

    def make_request(self, method: str, url: str, **kwargs) -> Tuple[bool, Any, str]:
        """Make HTTP request and handle errors"""
        try:
            if self.access_token and 'headers' not in kwargs:
                kwargs['headers'] = {'Authorization': f'Bearer {self.access_token}'}

            response = requests.request(method, url, timeout=30, **kwargs)

            # Try to parse JSON response
            try:
                data = response.json()
            except:
                data = response.text

            if 200 <= response.status_code < 300:
                return True, data, f"Status {response.status_code}"
            else:
                return False, data, f"Status {response.status_code}: {data}"
        except requests.exceptions.Timeout:
            return False, None, "Request timeout (30s)"
        except requests.exceptions.ConnectionError:
            return False, None, "Connection error"
        except Exception as e:
            return False, None, f"Error: {str(e)}"

    # ========== Base Endpoints Tests ==========

    def test_base_endpoints(self):
        """Test base health check endpoints"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}Testing Base Endpoints...{Colors.RESET}")

        # Test root endpoint
        success, data, msg = self.make_request('GET', BASE_URL)
        self.log_test('Base', 'GET /', success, msg)

        # Test health endpoint
        success, data, msg = self.make_request('GET', f"{BASE_URL}/health")
        self.log_test('Base', 'GET /health', success, msg)

        # Test debug endpoint
        success, data, msg = self.make_request('GET', f"{BASE_URL}/debug/db-schema")
        self.log_test('Base', 'GET /debug/db-schema', success, msg)

    # ========== Auth Endpoints Tests ==========

    def test_auth_endpoints(self):
        """Test authentication endpoints"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}Testing Auth Endpoints...{Colors.RESET}")

        # Test registration
        success, data, msg = self.make_request(
            'POST',
            f"{API_V1_URL}/auth/register",
            json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD
            }
        )
        self.log_test('Auth', 'POST /auth/register', success, msg)

        if success:
            self.access_token = data.get('access_token')

        # Test login
        success, data, msg = self.make_request(
            'POST',
            f"{API_V1_URL}/auth/login",
            json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD
            }
        )
        self.log_test('Auth', 'POST /auth/login', success, msg)

        if success and not self.access_token:
            self.access_token = data.get('access_token')

        # Test get current user (requires auth)
        if self.access_token:
            success, data, msg = self.make_request(
                'GET',
                f"{API_V1_URL}/auth/me",
                headers={'Authorization': f'Bearer {self.access_token}'}
            )
            self.log_test('Auth', 'GET /auth/me', success, msg)
        else:
            self.log_test('Auth', 'GET /auth/me', False, 'Skipped - no token')

    # ========== Constructor Endpoints Tests ==========

    def test_constructor_endpoints(self):
        """Test constructor endpoints"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}Testing Constructor Endpoints...{Colors.RESET}")

        # Test chat with meta-agent
        success, data, msg = self.make_request(
            'POST',
            f"{API_V1_URL}/constructor/chat",
            json={
                "user_id": TEST_USER_ID,
                "messages": [
                    {
                        "role": "user",
                        "content": "Привет! Хочу создать AI-агента для продажи курсов по программированию"
                    }
                ]
            }
        )
        self.log_test('Constructor', 'POST /constructor/chat', success, msg)

        if success and data.get('conversation_id'):
            self.test_conversation_id = data['conversation_id']

        # Test get user conversations
        success, data, msg = self.make_request(
            'GET',
            f"{API_V1_URL}/constructor/conversations/{TEST_USER_ID}"
        )
        self.log_test('Constructor', f'GET /constructor/conversations/{"{user_id}"}', success, msg)

        # Test get conversation history
        if self.test_conversation_id:
            success, data, msg = self.make_request(
                'GET',
                f"{API_V1_URL}/constructor/history/{self.test_conversation_id}"
            )
            self.log_test('Constructor', f'GET /constructor/history/{"{conversation_id}"}', success, msg)
        else:
            self.log_test('Constructor', 'GET /constructor/history/{conversation_id}', False, 'Skipped - no conversation_id')

    # ========== Agents Endpoints Tests ==========

    def test_agents_endpoints(self):
        """Test agents CRUD endpoints"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}Testing Agents Endpoints...{Colors.RESET}")

        # Test create agent manually
        success, data, msg = self.make_request(
            'POST',
            f"{API_V1_URL}/agents/create",
            json={
                "user_id": TEST_USER_ID,
                "agent_name": "Тестовый Агент Виктория",
                "business_type": "Продажа курсов по программированию",
                "knowledge_base": {
                    "services": ["Python курс", "JavaScript курс"],
                    "prices": ["5000 руб", "6000 руб"]
                },
                "status": "test"
            }
        )
        self.log_test('Agents', 'POST /agents/create', success, msg)

        if success and data.get('id'):
            self.test_agent_id = data['id']

        # Test get user agents
        success, data, msg = self.make_request(
            'GET',
            f"{API_V1_URL}/agents/{TEST_USER_ID}"
        )
        self.log_test('Agents', 'GET /agents/{user_id}', success, msg)

        # Test get specific agent
        if self.test_agent_id:
            success, data, msg = self.make_request(
                'GET',
                f"{API_V1_URL}/agents/detail/{self.test_agent_id}"
            )
            self.log_test('Agents', 'GET /agents/detail/{agent_id}', success, msg)
        else:
            self.log_test('Agents', 'GET /agents/detail/{agent_id}', False, 'Skipped - no agent_id')

        # Test update agent
        if self.test_agent_id:
            success, data, msg = self.make_request(
                'PUT',
                f"{API_V1_URL}/agents/{self.test_agent_id}",
                json={
                    "agent_name": "Тестовый Агент Виктория (Updated)"
                }
            )
            self.log_test('Agents', 'PUT /agents/{agent_id}', success, msg)
        else:
            self.log_test('Agents', 'PUT /agents/{agent_id}', False, 'Skipped - no agent_id')

        # Test agent test endpoint
        if self.test_agent_id:
            success, data, msg = self.make_request(
                'POST',
                f"{API_V1_URL}/agents/test",
                json={
                    "agent_id": self.test_agent_id,
                    "message": "Привет! Расскажи о курсах"
                }
            )
            self.log_test('Agents', 'POST /agents/test', success, msg)
        else:
            self.log_test('Agents', 'POST /agents/test', False, 'Skipped - no agent_id')

        # Test agent save (activate)
        if self.test_agent_id:
            success, data, msg = self.make_request(
                'POST',
                f"{API_V1_URL}/agents/save",
                json={
                    "agent_id": self.test_agent_id
                }
            )
            self.log_test('Agents', 'POST /agents/save', success, msg)
        else:
            self.log_test('Agents', 'POST /agents/save', False, 'Skipped - no agent_id')

        # Test pause agent
        if self.test_agent_id:
            success, data, msg = self.make_request(
                'POST',
                f"{API_V1_URL}/agents/{self.test_agent_id}/pause"
            )
            self.log_test('Agents', 'POST /agents/{agent_id}/pause', success, msg)
        else:
            self.log_test('Agents', 'POST /agents/{agent_id}/pause', False, 'Skipped - no agent_id')

        # Test resume agent
        if self.test_agent_id:
            success, data, msg = self.make_request(
                'POST',
                f"{API_V1_URL}/agents/{self.test_agent_id}/resume"
            )
            self.log_test('Agents', 'POST /agents/{agent_id}/resume', success, msg)
        else:
            self.log_test('Agents', 'POST /agents/{agent_id}/resume', False, 'Skipped - no agent_id')

        # Test chat with agent
        if self.test_agent_id:
            success, data, msg = self.make_request(
                'POST',
                f"{API_V1_URL}/agents/{self.test_agent_id}/chat",
                json={
                    "message": "Сколько стоит Python курс?"
                }
            )
            self.log_test('Agents', 'POST /agents/{agent_id}/chat', success, msg)
        else:
            self.log_test('Agents', 'POST /agents/{agent_id}/chat', False, 'Skipped - no agent_id')

        # Test delete agent (soft delete) - should be last
        if self.test_agent_id:
            success, data, msg = self.make_request(
                'DELETE',
                f"{API_V1_URL}/agents/{self.test_agent_id}"
            )
            self.log_test('Agents', 'DELETE /agents/{agent_id}', success, msg)
        else:
            self.log_test('Agents', 'DELETE /agents/{agent_id}', False, 'Skipped - no agent_id')

    # ========== Conversations Endpoints Tests ==========

    def test_conversations_endpoints(self):
        """Test conversations endpoints (requires auth)"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}Testing Conversations Endpoints...{Colors.RESET}")

        if not self.access_token:
            self.log_test('Conversations', 'GET /conversations/', False, 'Skipped - no auth token')
            self.log_test('Conversations', 'GET /conversations/{conversation_id}', False, 'Skipped - no auth token')
            return

        # Test list conversations
        success, data, msg = self.make_request(
            'GET',
            f"{API_V1_URL}/conversations/",
            headers={'Authorization': f'Bearer {self.access_token}'}
        )
        self.log_test('Conversations', 'GET /conversations/', success, msg)

        # Note: Detailed conversation endpoint requires valid conversation_id from agent interactions
        self.log_test('Conversations', 'GET /conversations/{conversation_id}', None, 'Skipped - requires actual conversation data')

    # ========== Billing Endpoints Tests ==========

    def test_billing_endpoints(self):
        """Test billing endpoints (requires auth)"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}Testing Billing Endpoints...{Colors.RESET}")

        if not self.access_token:
            self.log_test('Billing', 'GET /billing/current', False, 'Skipped - no auth token')
            return

        # Test get current billing
        success, data, msg = self.make_request(
            'GET',
            f"{API_V1_URL}/billing/current",
            headers={'Authorization': f'Bearer {self.access_token}'}
        )
        self.log_test('Billing', 'GET /billing/current', success, msg)

    # ========== Channels Endpoints Tests ==========

    def test_channels_endpoints(self):
        """Test channels endpoints"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}Testing Channels Endpoints...{Colors.RESET}")

        # Test get agent channels
        if self.test_agent_id:
            success, data, msg = self.make_request(
                'GET',
                f"{API_V1_URL}/channels/agent/{self.test_agent_id}"
            )
            self.log_test('Channels', 'GET /channels/agent/{agent_id}', success, msg)
        else:
            self.log_test('Channels', 'GET /channels/agent/{agent_id}', False, 'Skipped - no agent_id')

        # Note: Connect channel and webhook endpoints require actual credentials
        self.log_test('Channels', 'POST /channels/connect', None, 'Skipped - requires channel credentials')
        self.log_test('Channels', 'POST /channels/webhook/telegram/{channel_id}', None, 'Skipped - webhook endpoint')

    # ========== Run All Tests ==========

    def run_all_tests(self):
        """Run all API tests"""
        print(f"{Colors.BOLD}{'='*70}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.BLUE}Neuro-Seller API Testing Suite{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*70}{Colors.RESET}")
        print(f"Base URL: {BASE_URL}")
        print(f"Test User ID: {TEST_USER_ID}")
        print(f"Test Email: {TEST_EMAIL}")
        print(f"Timestamp: {datetime.now().isoformat()}")

        # Run all test categories
        self.test_base_endpoints()
        self.test_auth_endpoints()
        self.test_constructor_endpoints()
        self.test_agents_endpoints()
        self.test_conversations_endpoints()
        self.test_billing_endpoints()
        self.test_channels_endpoints()

        # Generate report
        self.generate_report()

    def generate_report(self):
        """Generate test report"""
        print(f"\n{Colors.BOLD}{'='*70}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.BLUE}Test Results Summary{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*70}{Colors.RESET}")

        # Count results
        total = len(self.results)
        passed = sum(1 for _, _, success, _ in self.results if success is True)
        failed = sum(1 for _, _, success, _ in self.results if success is False)
        skipped = sum(1 for _, _, success, _ in self.results if success is None)

        print(f"\nTotal Tests: {total}")
        print(f"{Colors.GREEN}Passed: {passed}{Colors.RESET}")
        print(f"{Colors.RED}Failed: {failed}{Colors.RESET}")
        print(f"{Colors.YELLOW}Skipped: {skipped}{Colors.RESET}")

        if failed > 0:
            print(f"\n{Colors.BOLD}{Colors.RED}Failed Tests:{Colors.RESET}")
            for category, endpoint, success, message in self.results:
                if success is False:
                    print(f"  {Colors.RED}✗{Colors.RESET} [{category}] {endpoint}: {message}")

        # Success rate
        if total > skipped:
            success_rate = (passed / (total - skipped)) * 100
            print(f"\n{Colors.BOLD}Success Rate: {success_rate:.1f}%{Colors.RESET}")

        print(f"\n{Colors.BOLD}{'='*70}{Colors.RESET}")

        # Save report to file
        self.save_report_to_file()

    def save_report_to_file(self):
        """Save detailed report to JSON file"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "base_url": BASE_URL,
            "test_user_id": TEST_USER_ID,
            "summary": {
                "total": len(self.results),
                "passed": sum(1 for _, _, s, _ in self.results if s is True),
                "failed": sum(1 for _, _, s, _ in self.results if s is False),
                "skipped": sum(1 for _, _, s, _ in self.results if s is None)
            },
            "results": [
                {
                    "category": cat,
                    "endpoint": ep,
                    "success": success,
                    "message": msg
                }
                for cat, ep, success, msg in self.results
            ]
        }

        filename = f"api_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"Detailed report saved to: {filename}")


def main():
    """Main entry point"""
    tester = APITester()
    try:
        tester.run_all_tests()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Testing interrupted by user{Colors.RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.RED}Fatal error: {e}{Colors.RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()

"""
Comprehensive test suite for all API flows.
Tests authentication, admin endpoints, worker processing, SSE, and topics.
"""
import asyncio
import os
import sys
from typing import Dict, Any

import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
ADMIN_TOKEN = os.getenv("CLERK_TEST_ADMIN_TOKEN", "")
USER_TOKEN = os.getenv("CLERK_TEST_USER_TOKEN", "")

class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.message = ""
        self.details = {}
    
    def success(self, message: str = "", details: Dict[str, Any] = None):
        self.passed = True
        self.message = message or "✅ PASSED"
        self.details = details or {}
    
    def failure(self, message: str, details: Dict[str, Any] = None):
        self.passed = False
        self.message = f"❌ FAILED: {message}"
        self.details = details or {}
    
    def __str__(self):
        status = "✅ PASS" if self.passed else "❌ FAIL"
        result = f"\n{status} | {self.name}\n"
        result += f"  {self.message}\n"
        if self.details:
            for key, value in self.details.items():
                result += f"  - {key}: {value}\n"
        return result


class APITester:
    def __init__(self):
        self.results = []
        self.admin_headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
        self.user_headers = {"Authorization": f"Bearer {USER_TOKEN}"}
    
    async def test_health(self) -> TestResult:
        """Test 1: Health check endpoint"""
        result = TestResult("Health Check")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{BASE_URL}/health", timeout=5.0)
                if response.status_code == 200:
                    data = response.json()
                    result.success("Server is healthy", {"status": data.get("status")})
                else:
                    result.failure(f"Status code: {response.status_code}")
        except Exception as e:
            result.failure(f"Connection error: {str(e)}")
        return result
    
    async def test_admin_auth(self) -> TestResult:
        """Test 2: Admin authentication and role"""
        result = TestResult("Admin Authentication")
        if not ADMIN_TOKEN:
            result.failure("CLERK_TEST_ADMIN_TOKEN not set in environment")
            return result
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{BASE_URL}/me",
                    headers=self.admin_headers,
                    timeout=5.0
                )
                if response.status_code == 200:
                    data = response.json()
                    role = data.get("role")
                    if role == "admin":
                        result.success(
                            "Admin authenticated successfully",
                            {"role": role, "id": data.get("id")}
                        )
                    else:
                        result.failure(f"Expected role='admin', got role='{role}'")
                else:
                    result.failure(f"Status code: {response.status_code}")
        except Exception as e:
            result.failure(f"Error: {str(e)}")
        return result
    
    async def test_user_auth(self) -> TestResult:
        """Test 3: Normal user authentication"""
        result = TestResult("User Authentication")
        if not USER_TOKEN:
            result.failure("CLERK_TEST_USER_TOKEN not set (optional, skip if only admin)")
            return result
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{BASE_URL}/me",
                    headers=self.user_headers,
                    timeout=5.0
                )
                if response.status_code == 200:
                    data = response.json()
                    result.success(
                        "User authenticated successfully",
                        {"role": data.get("role"), "id": data.get("id")}
                    )
                else:
                    result.failure(f"Status code: {response.status_code}")
        except Exception as e:
            result.failure(f"Error: {str(e)}")
        return result
    
    async def test_admin_create_topic(self) -> TestResult:
        """Test 4: Admin create topic endpoint"""
        result = TestResult("Admin Create Topic")
        if not ADMIN_TOKEN:
            result.failure("No admin token available")
            return result
        
        try:
            async with httpx.AsyncClient() as client:
                payload = {
                    "topic_name": "Test Algebra",
                    "topic_description": "Comprehensive algebra testing including equations, variables, and expressions for educational purposes.",
                    "params": {
                        "batch_size": 10,  # Small batch for testing
                        "language": "en"
                    }
                }
                response = await client.post(
                    f"{BASE_URL}/llm/admin/create-topic",
                    headers=self.admin_headers,
                    json=payload,
                    timeout=10.0
                )
                if response.status_code == 200:
                    data = response.json().get("data", {})
                    result.success(
                        "Topic creation job queued",
                        {
                            "job_id": data.get("job_id"),
                            "topic_slug": data.get("topic_slug"),
                            "batch_size": data.get("batch_size"),
                            "existing_topic": data.get("existing_topic")
                        }
                    )
                else:
                    result.failure(
                        f"Status code: {response.status_code}",
                        {"response": response.text}
                    )
        except Exception as e:
            result.failure(f"Error: {str(e)}")
        return result
    
    async def test_user_cannot_create_topic(self) -> TestResult:
        """Test 5: Normal user cannot create topics"""
        result = TestResult("User Permission Restriction")
        if not USER_TOKEN:
            result.failure("No user token available (skip test)")
            return result
        
        try:
            async with httpx.AsyncClient() as client:
                payload = {
                    "topic_name": "Unauthorized Topic",
                    "topic_description": "This should fail with 403",
                    "params": {"batch_size": 10}
                }
                response = await client.post(
                    f"{BASE_URL}/llm/admin/create-topic",
                    headers=self.user_headers,
                    json=payload,
                    timeout=10.0
                )
                if response.status_code == 403:
                    result.success("User correctly denied admin access (403 Forbidden)")
                else:
                    result.failure(
                        f"Expected 403, got {response.status_code}",
                        {"response": response.text}
                    )
        except Exception as e:
            result.failure(f"Error: {str(e)}")
        return result
    
    async def test_list_topics(self) -> TestResult:
        """Test 6: List all topics"""
        result = TestResult("List Topics")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{BASE_URL}/topics/search",
                    timeout=10.0
                )
                if response.status_code == 200:
                    data = response.json().get("data", {})
                    topics = data.get("topics", [])
                    result.success(
                        f"Retrieved {len(topics)} topics",
                        {"total_count": data.get("total_count")}
                    )
                else:
                    result.failure(f"Status code: {response.status_code}")
        except Exception as e:
            result.failure(f"Error: {str(e)}")
        return result
    
    async def test_list_jobs(self) -> TestResult:
        """Test 7: Admin list LLM jobs"""
        result = TestResult("List LLM Jobs")
        if not ADMIN_TOKEN:
            result.failure("No admin token available")
            return result
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{BASE_URL}/llm/admin/jobs",
                    headers=self.admin_headers,
                    timeout=10.0
                )
                if response.status_code == 200:
                    data = response.json().get("data", {})
                    jobs = data.get("jobs", [])
                    result.success(
                        f"Retrieved {len(jobs)} jobs",
                        {"count": len(jobs)}
                    )
                else:
                    result.failure(f"Status code: {response.status_code}")
        except Exception as e:
            result.failure(f"Error: {str(e)}")
        return result
    
    async def test_sse_quiz_start(self) -> TestResult:
        """Test 8: SSE quiz start endpoint"""
        result = TestResult("SSE Quiz Start")
        if not ADMIN_TOKEN:
            result.failure("No admin token available")
            return result
        
        try:
            # First get a topic to test with
            async with httpx.AsyncClient() as client:
                topics_response = await client.get(
                    f"{BASE_URL}/topics/search",
                    timeout=10.0
                )
                
                if topics_response.status_code != 200:
                    result.failure("Could not fetch topics for SSE test")
                    return result
                
                topics_data = topics_response.json().get("data", {})
                topics = topics_data.get("topics", [])
                
                if not topics:
                    result.failure("No topics available for SSE test (need to run worker first)")
                    return result
                
                topic_id = topics[0].get("topic_uid") or topics[0].get("slug")
                
                # Test SSE connection (will timeout after short period)
                try:
                    sse_response = await client.get(
                        f"{BASE_URL}/sse/quiz/start",
                        params={"topic_id": topic_id},
                        headers=self.admin_headers,
                        timeout=3.0  # Short timeout
                    )
                    result.failure("SSE should keep connection open (timeout expected)")
                except httpx.ReadTimeout:
                    result.success(
                        "SSE connection established (timed out as expected)",
                        {"topic_id": topic_id}
                    )
        except Exception as e:
            result.failure(f"Error: {str(e)}")
        return result
    
    async def test_profile_endpoint(self) -> TestResult:
        """Test 9: User profile endpoint"""
        result = TestResult("Profile Endpoint")
        if not ADMIN_TOKEN:
            result.failure("No admin token available")
            return result
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{BASE_URL}/profile/me",
                    headers=self.admin_headers,
                    timeout=10.0
                )
                if response.status_code == 200:
                    data = response.json().get("data", {})
                    result.success(
                        "Profile retrieved",
                        {
                            "profile_complete": data.get("profile_complete"),
                            "subjects": len(data.get("subjects_of_interest") or [])
                        }
                    )
                else:
                    result.failure(f"Status code: {response.status_code}")
        except Exception as e:
            result.failure(f"Error: {str(e)}")
        return result
    
    async def run_all_tests(self):
        """Run all tests and generate report"""
        print("\n" + "=" * 70)
        print("🧪 COMPREHENSIVE API TEST SUITE")
        print("=" * 70)
        print(f"Base URL: {BASE_URL}")
        print(f"Admin Token: {'✅ Set' if ADMIN_TOKEN else '❌ Not set'}")
        print(f"User Token: {'✅ Set' if USER_TOKEN else '⚠️  Not set (optional)'}")
        print("=" * 70)
        
        # Run all tests
        tests = [
            self.test_health(),
            self.test_admin_auth(),
            self.test_user_auth(),
            self.test_list_topics(),
            self.test_admin_create_topic(),
            self.test_user_cannot_create_topic(),
            self.test_list_jobs(),
            self.test_profile_endpoint(),
            self.test_sse_quiz_start(),
        ]
        
        results = await asyncio.gather(*tests)
        self.results = results
        
        # Print results
        for r in results:
            print(r)
        
        # Summary
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        print("=" * 70)
        print(f"📊 SUMMARY: {passed}/{total} tests passed")
        print("=" * 70)
        
        if passed == total:
            print("🎉 ALL TESTS PASSED!")
            return 0
        else:
            print("⚠️  SOME TESTS FAILED - Check details above")
            return 1


async def main():
    """Main test runner"""
    tester = APITester()
    exit_code = await tester.run_all_tests()
    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())

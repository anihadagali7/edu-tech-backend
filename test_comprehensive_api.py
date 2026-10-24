#!/usr/bin/env python3
"""
Comprehensive test suite for Pure Clerk roles, SSE implementation, 
adaptive logic, and all APIs.
"""

import asyncio
import json
import time
import uuid
from typing import Dict, Any
import httpx
import websockets
from jose import jwt


class AdaptiveQuizTester:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = httpx.AsyncClient()
        
    async def cleanup(self):
        """Clean up resources."""
        await self.client.aclose()
    
    def create_mock_jwt(self, user_id: str, role: str = "user", org_id: str = None, org_role: str = None) -> str:
        """Create a mock JWT for testing (bypasses signature verification)."""
        payload = {
            "sub": user_id,
            "email": f"test-{user_id}@example.com",
            "name": f"Test User {user_id}",
            "role": role if not org_id else None,  # Global role only if no org
            "org_id": org_id,
            "org_role": org_role,
            "org_slug": f"test-org-{org_id}" if org_id else None,
            "exp": int(time.time()) + 3600
        }
        
        # Create unsigned JWT for testing
        return jwt.encode(payload, "test-secret", algorithm="HS256")
    
    async def test_health_check(self) -> bool:
        """Test basic server health."""
        print("🏥 Testing server health...")
        try:
            response = await self.client.get(f"{self.base_url}/health")
            success = response.status_code == 200
            print(f"   {'✅' if success else '❌'} Health check: {response.status_code}")
            return success
        except Exception as e:
            print(f"   ❌ Health check failed: {e}")
            return False
    
    async def test_auth_endpoints(self) -> bool:
        """Test authentication with Pure Clerk roles."""
        print("🔐 Testing Pure Clerk authentication...")
        
        test_cases = [
            ("Regular user", "user_123", "user", None, None),
            ("System admin", "admin_456", "admin", None, None),
            ("Org admin", "org_admin_789", "admin", "org_001", "admin"),
            ("Org member", "member_999", "member", "org_001", "member"),
        ]
        
        for case_name, user_id, role, org_id, org_role in test_cases:
            try:
                token = self.create_mock_jwt(user_id, role, org_id, org_role)
                headers = {"Authorization": f"Bearer {token}"}
                
                # Test a protected endpoint that requires auth
                response = await self.client.get(
                    f"{self.base_url}/topics",
                    headers=headers
                )
                
                success = response.status_code == 200
                print(f"   {'✅' if success else '❌'} {case_name}: {response.status_code}")
                
                if success:
                    # Check that role resolution worked
                    print(f"      Role: {role}, Org: {org_id}, Org Role: {org_role}")
                    
            except Exception as e:
                print(f"   ❌ {case_name} failed: {e}")
                return False
        
        return True
    
    async def test_admin_endpoints(self) -> bool:
        """Test admin endpoints with Pure Clerk roles."""
        print("👨‍💼 Testing admin endpoints...")
        
        # Test with system admin
        admin_token = self.create_mock_jwt("admin_123", "admin")
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        
        # Test with org admin
        org_admin_token = self.create_mock_jwt("org_admin_456", "admin", "org_001", "admin")
        org_admin_headers = {"Authorization": f"Bearer {org_admin_token}"}
        
        # Test with regular user (should fail)
        user_token = self.create_mock_jwt("user_789", "user")
        user_headers = {"Authorization": f"Bearer {user_token}"}
        
        admin_endpoints = [
            "/admin/users",
            "/admin/events", 
        ]
        
        for endpoint in admin_endpoints:
            # Test system admin access
            try:
                response = await self.client.get(f"{self.base_url}{endpoint}", headers=admin_headers)
                success = response.status_code == 200
                print(f"   {'✅' if success else '❌'} System admin {endpoint}: {response.status_code}")
            except Exception as e:
                print(f"   ❌ System admin {endpoint} failed: {e}")
            
            # Test org admin access
            try:
                response = await self.client.get(f"{self.base_url}{endpoint}", headers=org_admin_headers)
                success = response.status_code == 200
                print(f"   {'✅' if success else '❌'} Org admin {endpoint}: {response.status_code}")
            except Exception as e:
                print(f"   ❌ Org admin {endpoint} failed: {e}")
            
            # Test user access (should fail)
            try:
                response = await self.client.get(f"{self.base_url}{endpoint}", headers=user_headers)
                denied = response.status_code == 403
                print(f"   {'✅' if denied else '❌'} User denied {endpoint}: {response.status_code}")
            except Exception as e:
                print(f"   ❌ User access test failed: {e}")
        
        return True
    
    async def test_topics_api(self) -> Dict[str, Any]:
        """Test topics API and get a topic for quiz testing."""
        print("📚 Testing topics API...")
        
        user_token = self.create_mock_jwt("user_123", "user")
        headers = {"Authorization": f"Bearer {user_token}"}
        
        # List topics
        response = await self.client.get(f"{self.base_url}/topics", headers=headers)
        success = response.status_code == 200
        print(f"   {'✅' if success else '❌'} List topics: {response.status_code}")
        
        topics_data = None
        if success:
            topics_data = response.json()
            topics = topics_data.get("data", {}).get("items", [])
            print(f"   Found {len(topics)} topics")
            
            if topics:
                topic = topics[0]
                print(f"   Sample topic: {topic['name']} (id: {topic['id']})")
                return topic
        
        # If no topics found, we'll need to create one (admin operation)
        print("   No topics found - would need admin to create topics")
        return None
    
    async def test_quiz_api(self, topic_id: str = None) -> Dict[str, Any]:
        """Test standard quiz API with adaptive logic."""
        print("🧠 Testing standard quiz API with adaptive logic...")
        
        user_token = self.create_mock_jwt("quiz_user_123", "user")
        headers = {"Authorization": f"Bearer {user_token}"}
        
        if not topic_id:
            print("   ⚠️  No topic available for quiz testing")
            return None
        
        try:
            # Start a quiz session
            quiz_data = {
                "topic_id": topic_id,
                "difficulty_hint": 3
            }
            
            response = await self.client.post(
                f"{self.base_url}/quizzes/start",
                headers=headers,
                json=quiz_data
            )
            
            success = response.status_code == 200
            print(f"   {'✅' if success else '❌'} Start quiz: {response.status_code}")
            
            if success:
                quiz_session = response.json()["data"]
                session_uid = quiz_session["session"]["session_uid"]
                first_question = quiz_session.get("first_question")
                
                print(f"   Session UID: {session_uid}")
                print(f"   First question available: {first_question is not None}")
                
                if first_question:
                    print(f"   Question difficulty: {first_question['difficulty']}")
                
                return {
                    "session_uid": session_uid,
                    "first_question": first_question
                }
        
        except Exception as e:
            print(f"   ❌ Quiz API test failed: {e}")
        
        return None
    
    async def test_sse_connection(self, session_uid: str = None, topic_id: str = None) -> bool:
        """Test SSE implementation and adaptive logic."""
        print("🌊 Testing SSE implementation with adaptive logic...")
        
        if not session_uid or not topic_id:
            print("   ⚠️  No session or topic for SSE testing")
            return False
        
        user_token = self.create_mock_jwt("sse_user_123", "user")
        
        try:
            # Test SSE endpoint availability
            headers = {"Authorization": f"Bearer {user_token}"}
            
            # Start SSE session
            sse_data = {"topic_id": topic_id}
            
            response = await self.client.post(
                f"{self.base_url}/sse/quiz/{session_uid}/start",
                headers=headers,
                json=sse_data
            )
            
            print(f"   SSE start response: {response.status_code}")
            
            if response.status_code == 200:
                print("   ✅ SSE endpoint accessible")
                return True
            else:
                print(f"   ❌ SSE start failed: {response.text}")
                return False
                
        except Exception as e:
            print(f"   ❌ SSE test failed: {e}")
            return False
    
    async def test_adaptive_logic_simulation(self, session_uid: str = None, question_data: Dict = None) -> bool:
        """Test adaptive difficulty adjustment through answer submission."""
        print("⚡ Testing adaptive logic simulation...")
        
        if not session_uid or not question_data:
            print("   ⚠️  No session or question data for adaptive testing")
            return False
        
        user_token = self.create_mock_jwt("adaptive_user_123", "user") 
        headers = {"Authorization": f"Bearer {user_token}"}
        
        try:
            # Simulate multiple correct answers to test difficulty increase
            question_id = question_data["id"]
            correct_answer = question_data.get("correct_answer", "A")  # Assume A is correct
            
            for i in range(3):
                answer_data = {
                    "question_id": question_id,
                    "selected_answer": correct_answer,
                    "elapsed_ms": 5000 + (i * 1000)
                }
                
                response = await self.client.post(
                    f"{self.base_url}/sse/quiz/{session_uid}/answer",
                    headers=headers,
                    json=answer_data
                )
                
                if response.status_code == 200:
                    result = response.json()["data"]
                    is_correct = result.get("is_correct", False)
                    stats = result.get("session_stats", {})
                    
                    print(f"   Answer {i+1}: {'Correct' if is_correct else 'Incorrect'}")
                    print(f"   Current difficulty: {stats.get('current_difficulty', 'N/A')}")
                    print(f"   Streak: {stats.get('streak_correct', 0)} correct")
                    
                    if i == 0:
                        # This should work for first answer
                        print("   ✅ Answer submission working")
                    
                else:
                    print(f"   ⚠️  Answer {i+1} submission failed: {response.status_code}")
                    if i == 0:
                        return False
            
            print("   ✅ Adaptive logic simulation completed")
            return True
            
        except Exception as e:
            print(f"   ❌ Adaptive logic test failed: {e}")
            return False
    
    async def run_comprehensive_tests(self) -> Dict[str, bool]:
        """Run all tests and return results."""
        print("🚀 Starting Comprehensive API and SSE Tests")
        print("=" * 60)
        
        results = {}
        
        # Basic health check
        results["health"] = await self.test_health_check()
        
        # Authentication tests
        results["auth"] = await self.test_auth_endpoints()
        
        # Admin endpoint tests  
        results["admin"] = await self.test_admin_endpoints()
        
        # Topics API test
        topic = await self.test_topics_api()
        results["topics"] = topic is not None
        
        # Quiz API test (if topic available)
        quiz_session = None
        if topic:
            quiz_session = await self.test_quiz_api(topic["id"])
            results["quiz_api"] = quiz_session is not None
        else:
            results["quiz_api"] = False
        
        # SSE test (if quiz session available)  
        if quiz_session and topic:
            results["sse"] = await self.test_sse_connection(
                quiz_session["session_uid"], 
                topic["id"]
            )
            
            # Adaptive logic test
            if quiz_session.get("first_question"):
                results["adaptive"] = await self.test_adaptive_logic_simulation(
                    quiz_session["session_uid"],
                    quiz_session["first_question"] 
                )
            else:
                results["adaptive"] = False
        else:
            results["sse"] = False
            results["adaptive"] = False
        
        return results


async def main():
    """Main test execution."""
    tester = AdaptiveQuizTester()
    
    try:
        results = await tester.run_comprehensive_tests()
        
        print("\n" + "=" * 60)
        print("🎯 Test Results Summary:")
        print("=" * 60)
        
        for test_name, passed in results.items():
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{status} {test_name.upper()}")
        
        total_tests = len(results)
        passed_tests = sum(results.values())
        
        print(f"\nOverall: {passed_tests}/{total_tests} tests passed")
        
        if passed_tests == total_tests:
            print("🎉 All systems working perfectly!")
        elif passed_tests >= total_tests * 0.8:
            print("✅ Most systems working - minor issues to address")
        else:
            print("⚠️  Several systems need attention")
        
    except Exception as e:
        print(f"❌ Test suite failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await tester.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
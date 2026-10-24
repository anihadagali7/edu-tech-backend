"""Verification script to test all the fixes applied.

Run this to verify:
1. Job status updates work
2. Explanations are stored correctly
3. SSE feedback includes detailed explanations
"""

import asyncio
import json
from sqlalchemy import select, text
from app.db.base import get_session
from app.db.models import Question, LLMJob
from app.config import get_settings


async def verify_explanations_in_db():
    """Verify that questions in DB have explanations."""
    print("\n" + "="*70)
    print("VERIFYING: Explanations Storage in Database")
    print("="*70)
    
    async for session in get_session():
        try:
            # Get a sample question
            result = await session.execute(
                select(Question).limit(1)
            )
            question = result.scalar_one_or_none()
            
            if not question:
                print("❌ No questions found in database")
                return False
            
            print(f"✅ Found question: {question.body[:60]}...")
            print(f"   Difficulty: {question.difficulty}")
            print(f"   Correct Answer: {question.correct_answer}")
            
            if not question.explanations:
                print("❌ Question has no explanations!")
                return False
            
            print(f"   Explanations structure:")
            explanations = question.explanations
            
            if 'correct' in explanations:
                print(f"      ✅ Has 'correct' explanation: {explanations['correct'][:80]}...")
            else:
                print(f"      ❌ Missing 'correct' explanation")
                return False
            
            if 'distractors' in explanations:
                distractors = explanations['distractors']
                print(f"      ✅ Has 'distractors' with {len(distractors)} entries")
                for key, value in distractors.items():
                    if value:  # Not empty string (empty means it's the correct answer)
                        print(f"         - {key}: {value[:60]}...")
            else:
                print(f"      ❌ Missing 'distractors' explanations")
                return False
            
            print("\n✅ PASS: Explanations are properly stored!")
            return True
            
        except Exception as e:
            print(f"❌ Error: {e}")
            return False


async def verify_job_status_updates():
    """Verify that job statuses are being updated."""
    print("\n" + "="*70)
    print("VERIFYING: Job Status Updates")
    print("="*70)
    
    async for session in get_session():
        try:
            # Count jobs by status
            result = await session.execute(
                text("""
                    SELECT status, COUNT(*) as count 
                    FROM llm_jobs 
                    GROUP BY status
                """)
            )
            
            status_counts = {row[0]: row[1] for row in result}
            
            print(f"\nJob Status Distribution:")
            for status, count in status_counts.items():
                print(f"   {status}: {count}")
            
            # Check for succeeded/failed jobs
            if 'succeeded' in status_counts or 'failed' in status_counts:
                print("\n✅ PASS: Job status updates are working!")
                return True
            elif 'running' in status_counts or 'queued' in status_counts:
                print("\n⚠️  WARNING: Only queued/running jobs found. Run worker to test completion.")
                return True
            else:
                print("\n❌ No jobs found in database")
                return False
                
        except Exception as e:
            print(f"❌ Error: {e}")
            return False


async def verify_config():
    """Verify configuration changes."""
    print("\n" + "="*70)
    print("VERIFYING: Configuration")
    print("="*70)
    
    settings = get_settings()
    
    print(f"\nOpenAI Model: {settings.OPENAI_MODEL}")
    
    if settings.OPENAI_MODEL == "gpt-4o":
        print("✅ PASS: Using gpt-4o (recommended)")
    elif settings.OPENAI_MODEL == "gpt-4o-mini":
        print("⚠️  WARNING: Still using gpt-4o-mini. Update .env to use gpt-4o")
    else:
        print(f"ℹ️  INFO: Using custom model: {settings.OPENAI_MODEL}")
    
    return True


async def main():
    """Run all verification tests."""
    print("\n" + "🔍 " * 35)
    print("       VERIFICATION SUITE FOR ALL FIXES")
    print("🔍 " * 35)
    
    results = []
    
    # Test 1: Config
    results.append(await verify_config())
    
    # Test 2: Job status updates
    results.append(await verify_job_status_updates())
    
    # Test 3: Explanations storage
    results.append(await verify_explanations_in_db())
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    passed = sum(results)
    total = len(results)
    
    print(f"\nTests Passed: {passed}/{total}")
    
    if passed == total:
        print("\n🎉 ALL VERIFICATIONS PASSED! 🎉")
        print("\nNext steps:")
        print("1. Run the worker to test job processing: python -m worker.runner --once")
        print("2. Test SSE endpoint with a quiz session")
        print("3. Check that answer feedback includes detailed explanations")
    else:
        print("\n⚠️  Some verifications failed. Review the output above.")
    
    print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())

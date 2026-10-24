"""
Cleanup script to remove redundant test files and old documentation.
Run this to clean up the repository.
"""
import os
from pathlib import Path

# Files to delete
FILES_TO_DELETE = [
    # Old test files (keeping only test_all_flows.py and tests/ directory)
    "test_uuid_fix.py",
    "test_topics_direct.py",
    "test_sse_session_fix.py",
    "test_sse_integration.py",
    "test_sse_flow.py",
    "test_sse_adaptive_workflow.py",
    "test_simple_api.py",
    "test_server_health.py",
    "test_real_adaptive_system.py",
    "test_pure_clerk_direct.py",
    "test_live_adaptive_quiz.py",
    "test_final_demonstration.py",
    "test_db_url.py",
    "test_create_job.py",
    "test_comprehensive_api.py",
    "test_complete_workflow.py",
    "test_complete_system_final.py",
    "test_auth_debug.py",
    
    # Old documentation files (keeping only new README)
    "LLM_WORKER_README.md",
    "IMPLEMENTATION_STATUS.md",
    "IMPLEMENTATION_COMPLETE.md",
    "FIXES_SUMMARY.md",
    "SIMPLIFIED_PLAN_NO_ORGS.md",
    "SESSION_CLOSE_IMPLEMENTED.md",
    "QUICK_START.md",
    "QUICK_ACTION_SUMMARY.md",
    "PURE_CLERK_ROLES.md",
    "ORGANIZATION_ROLES_PLAN.md",
    "SSE_BUG_FIX_SUMMARY.md",
    "CURRENT_CODE_ISSUES.md",
    "COMPLETE_SYSTEM_STATUS.md",
    "CLERK_ORGANIZATION_ROLES.md",
    "SSE_INTEGRATION_COMPLETE.md",
    "SSE_QUICK_REFERENCE.md",
    "SSE_IMPLEMENTATION_COMPLETE.md",
    "YOUR_QUESTIONS_ANSWERED.md",
    "TOPIC_CONFIRMATION.md",
    "TESTING_GUIDE.md",
    
    # Miscellaneous old files
    "debug_workflow.py",
    "sse_quiz_demo.html",
    "SSE_QUIZ_IMPLEMENTATION.md",
]

def main():
    """Delete redundant files"""
    root = Path(__file__).parent
    deleted = []
    not_found = []
    
    print("🧹 Cleaning up redundant files...\n")
    
    for file in FILES_TO_DELETE:
        file_path = root / file
        if file_path.exists():
            try:
                file_path.unlink()
                deleted.append(file)
                print(f"✅ Deleted: {file}")
            except Exception as e:
                print(f"❌ Failed to delete {file}: {e}")
        else:
            not_found.append(file)
    
    print(f"\n📊 Summary:")
    print(f"  - Deleted: {len(deleted)} files")
    print(f"  - Not found: {len(not_found)} files")
    
    if deleted:
        print(f"\n✨ Cleanup complete!")
        print(f"\n📝 Kept files:")
        print(f"  - README_NEW.md (main documentation)")
        print(f"  - test_all_flows.py (comprehensive test suite)")
        print(f"  - tests/ directory (unit tests)")
        print(f"\n💡 Next step: Rename README_NEW.md to README.md")
        print(f"   mv README_NEW.md README.md")
    
    if not_found:
        print(f"\n⚠️  Some files were not found (may have been deleted already):")
        for file in not_found[:5]:  # Show first 5
            print(f"  - {file}")
        if len(not_found) > 5:
            print(f"  ... and {len(not_found) - 5} more")


if __name__ == "__main__":
    main()

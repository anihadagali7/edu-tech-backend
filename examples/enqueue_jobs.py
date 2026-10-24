#!/usr/bin/env python3
"""Example script for managing LLM jobs and pending topic requests.

This script demonstrates the new admin approval workflow:
1. Users search for topics via GET /topics/search
2. If no matches found, frontend shows confirmation dialog 
3. Users confirm via POST /topics/request-topic (creates PendingTopic)
4. Admins review pending requests via GET /admin/llm/pending-topics
5. Admins approve requests via POST /admin/llm/approve/{topic_slug} (creates LLMJob)
6. Workers process LLM jobs to generate topics and questions

Usage:
    python examples/enqueue_jobs.py requests     # Create sample pending requests
    python examples/enqueue_jobs.py list-requests # List all pending requests
    python examples/enqueue_jobs.py approve <slug> '<description>' # Approve a request
    python examples/enqueue_jobs.py list-jobs    # List all LLM jobs
    python examples/enqueue_jobs.py status [job_id] # Show job status
"""

import asyncio
import json
import sys
import uuid
from datetime import datetime

from app.db.base import get_session
from app.db.models import LLMJob, PendingTopic


async def create_sample_pending_requests():
    """Create sample pending topic requests (simulates user search behavior)."""
    
    requests_to_create = [
        {
            "topic_slug": "linear-algebra",
            "display_name": "Linear Algebra",
        },
        {
            "topic_slug": "calculus-basics", 
            "display_name": "Calculus Fundamentals",
        },
        {
            "topic_slug": "python-programming",
            "display_name": "Python Programming",
        },
        {
            "topic_slug": "machine-learning",
            "display_name": "Machine Learning Basics",
        }
    ]
    
    async with get_session() as session:
        created_requests = []
        
        for request_data in requests_to_create:
            # Check if already exists
            from sqlalchemy import select
            existing_stmt = select(PendingTopic).where(
                PendingTopic.topic_slug == request_data["topic_slug"]
            )
            existing = await session.execute(existing_stmt)
            if existing.scalar_one_or_none():
                print(f"⚠️  Request already exists: {request_data['display_name']}")
                continue
                
            request = PendingTopic(
                topic_slug=request_data["topic_slug"],
                display_name=request_data["display_name"],
                status="queued",
                requested_by=None,  # Anonymous request for demo
            )
            
            session.add(request)
            created_requests.append(request)
        
        await session.commit()
        
        print(f"✅ Created {len(created_requests)} sample topic requests:")
        for request in created_requests:
            print(f"  - {request.topic_slug}: {request.display_name}")
        
        return created_requests


async def list_pending_requests():
    """List all pending topic requests."""
    
    async with get_session() as session:
        from sqlalchemy import select
        stmt = select(PendingTopic).where(PendingTopic.status == "queued")
        result = await session.execute(stmt)
        requests = result.scalars().all()
        
        if not requests:
            print("📭 No pending topic requests found")
            return
            
        print(f"📋 Found {len(requests)} pending topic requests:")
        print("─" * 80)
        for request in requests:
            print(f"Slug: {request.topic_slug}")
            print(f"Name: {request.display_name}")
            print(f"Status: {request.status}")
            print(f"Created: {request.created_at}")
            print("─" * 80)


async def approve_pending_request(topic_slug: str, admin_description: str):
    """Simulate admin approving a topic request by creating an LLM job."""
    
    async with get_session() as session:
        # Find the pending request
        from sqlalchemy import select, update
        stmt = select(PendingTopic).where(
            PendingTopic.topic_slug == topic_slug,
            PendingTopic.status == "queued"
        )
        result = await session.execute(stmt)
        pending = result.scalar_one_or_none()
        
        if not pending:
            print(f"❌ No pending request found for topic: {topic_slug}")
            return
            
        # Create LLM job
        job = LLMJob(
            job_type="create_topic_questions",
            status="queued",
            params={
                "topic_name": pending.display_name,
                "admin_description": admin_description,
                "source": "admin_approved"
            },
            priority=1,
            created_by=None,  # Admin action
        )
        
        session.add(job)
        
        # Update pending topic status
        update_stmt = update(PendingTopic).where(
            PendingTopic.id == pending.id
        ).values(status="approved")
        
        await session.execute(update_stmt)
        await session.commit()
        
        print(f"✅ Approved topic request: {topic_slug}")
        print(f"📝 Created LLM job: {job.id}")
        print(f"📋 Description: {admin_description}")


async def list_pending_jobs():
    """List all LLM jobs."""
    
    async with get_session() as session:
        from sqlalchemy import select
        stmt = select(LLMJob).order_by(LLMJob.created_at.desc())
        result = await session.execute(stmt)
        jobs = result.scalars().all()
        
        if not jobs:
            print("📭 No LLM jobs found")
            return
            
        print(f"🔄 Found {len(jobs)} LLM jobs:")
        print("─" * 100)
        for job in jobs:
            topic_name = job.params.get("topic_name", "N/A") if job.params else "N/A"
            print(f"ID: {job.id}")
            print(f"Type: {job.job_type}")
            print(f"Status: {job.status}")
            print(f"Topic: {topic_name}")
            print(f"Priority: {job.priority}")
            print(f"Created: {job.created_at}")
            if job.started_at:
                print(f"Started: {job.started_at}")
            if job.completed_at:
                print(f"Completed: {job.completed_at}")
            print("─" * 100)


async def show_job_status(job_id: str = None):
    """Show status of specific job or recent jobs."""
    
    async with get_session() as session:
        from sqlalchemy import select
        
        if job_id:
            # Show specific job
            stmt = select(LLMJob).where(LLMJob.id == uuid.UUID(job_id))
            result = await session.execute(stmt)
            job = result.scalar_one_or_none()
            
            if not job:
                print(f"❌ Job not found: {job_id}")
                return
                
            print(f"📋 Job Details: {job.id}")
            print("─" * 60)
            print(f"Type: {job.job_type}")
            print(f"Status: {job.status}")
            print(f"Priority: {job.priority}")
            print(f"Created: {job.created_at}")
            if job.started_at:
                print(f"Started: {job.started_at}")
            if job.completed_at:
                print(f"Completed: {job.completed_at}")
            if job.params:
                print(f"Params: {json.dumps(job.params, indent=2)}")
            if job.result:
                print(f"Result: {json.dumps(job.result, indent=2)}")
            if job.error_message:
                print(f"Error: {job.error_message}")
        else:
            # Show recent jobs summary
            stmt = select(LLMJob).order_by(LLMJob.created_at.desc()).limit(10)
            result = await session.execute(stmt)
            jobs = result.scalars().all()
            
            if not jobs:
                print("📭 No jobs found")
                return
                
            print("📊 Recent Jobs Summary:")
            print("─" * 80)
            for job in jobs:
                status_emoji = {
                    "queued": "⏳",
                    "in_progress": "🔄", 
                    "completed": "✅",
                    "failed": "❌"
                }.get(job.status, "❓")
                
                topic_name = job.params.get("topic_name", "N/A") if job.params else "N/A"
                print(f"{status_emoji} {job.id} | {job.status} | {topic_name}")
            print("─" * 80)


async def main():
    """Main function to handle command line arguments."""
    
    if len(sys.argv) < 2:
        print("Usage: python examples/enqueue_jobs.py <command> [args...]")
        print("")
        print("Commands:")
        print("  requests                    Create sample pending topic requests")
        print("  list-requests               List all pending topic requests")
        print("  approve <slug> '<desc>'     Approve a pending request")
        print("  list-jobs                   List all LLM jobs")
        print("  status [job_id]             Show job status (specific or recent)")
        print("")
        print("Example workflow:")
        print("  1. python examples/enqueue_jobs.py requests")
        print("  2. python examples/enqueue_jobs.py list-requests")
        print("  3. python examples/enqueue_jobs.py approve linear-algebra 'Linear algebra fundamentals'")
        print("  4. python examples/enqueue_jobs.py list-jobs")
        return
    
    command = sys.argv[1]
    
    if command == "requests":
        await create_sample_pending_requests()
    elif command == "list-requests":
        await list_pending_requests()
    elif command == "approve":
        if len(sys.argv) < 4:
            print("Usage: approve <topic-slug> '<description>'")
            return 1
        topic_slug = sys.argv[2]
        description = sys.argv[3]
        await approve_pending_request(topic_slug, description)
    elif command == "list-jobs":
        await list_pending_jobs()
    elif command == "status":
        job_id = sys.argv[2] if len(sys.argv) > 2 else None
        await show_job_status(job_id)
    else:
        print(f"❌ Unknown command: {command}")
        return 1


if __name__ == "__main__":
    asyncio.run(main())
import asyncio
from app.db.models import LLMJob
from app.db.base import SessionLocal
from sqlalchemy import select, desc
from app.db import models_study


async def main():
    async with SessionLocal() as session:
        # Check latest learning material job
        result = await session.execute(
            select(LLMJob)
            .where(LLMJob.job_type == "learning_material_generation")
            .order_by(LLMJob.created_at.desc())
            .limit(1)
        )
        job = result.scalar_one_or_none()
        
        if not job:
            print("No learning material generation jobs found")
            return
        
        print(f"=== Last Learning Material Job ===")
        print(f"Job ID: {job.id}")
        print(f"Status: {job.status}")
        print(f"Topic: {job.topic_name} ({job.topic_slug})")
        print(f"Created count: {job.created_count}")
        print(f"Error: {job.error}")
        
        if job.params:
            material_id = job.params.get("material_id")
            print(f"Material ID from job: {material_id}")
            
            if material_id:
                # Check if material exists in DB
                mat_result = await session.execute(
                    select(models_study.LearningMaterial)
                    .where(models_study.LearningMaterial.id == material_id)
                )
                material = mat_result.scalar_one_or_none()
                
                if material:
                    print(f"\n=== Learning Material ===")
                    print(f"Material ID: {material.id}")
                    print(f"Title: {material.title}")
                    print(f"Status: {material.status}")
                    print(f"Summary length: {len(material.summary) if material.summary else 0}")
                    print(f"Content length: {len(material.content_markdown) if material.content_markdown else 0}")
                    
                    # Check sections
                    sections_result = await session.execute(
                        select(models_study.LearningSection)
                        .where(models_study.LearningSection.material_id == material.id)
                        .order_by(models_study.LearningSection.position)
                    )
                    sections = sections_result.scalars().all()
                    
                    print(f"\n=== Learning Sections ({len(sections)} total) ===")
                    for sec in sections:
                        print(f"  [{sec.position}] {sec.title}")
                        print(f"      Content length: {len(sec.content_markdown) if sec.content_markdown else 0}")
                else:
                    print(f"\nWARNING: Material with ID {material_id} not found in database!")
        else:
            print("No params in job")


if __name__ == "__main__":
    asyncio.run(main())

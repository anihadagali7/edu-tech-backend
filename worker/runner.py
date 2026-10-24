"""LLM worker runner for processing queued topic generation jobs.

This module processes LLM jobs by:
1. Claiming queued jobs atomically
2. Calling OpenAI via LangChain with structured prompts
3. Validating JSON responses with Pydantic
4. Upserting topics and questions with deduplication
5. Emitting events and updating job status

Usage:
    python -m worker.runner --once    # Process one job and exit
    python -m worker.runner --loop    # Process up to N jobs per run
    
Environment Variables:
    OPENAI_API_KEY: Required OpenAI API key
    OPENAI_MODEL: Model to use (default: gpt-4o-mini)  
    DATABASE_URL: PostgreSQL connection string
    
Example SQL to enqueue a job:
    INSERT INTO llm_jobs (id, status, topic_slug, topic_name, params)
    VALUES (gen_random_uuid(), 'queued', 'linear-algebra', 'Linear Algebra',
            jsonb_build_object('batch_size', 20, 'language', 'en',
                               'topic_hint_description', 'vectors, matrices, eigenvalues'));
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import traceback
from typing import Any, Dict


try:
    from langchain_openai import ChatOpenAI
    from langchain.schema import BaseMessage
except ImportError:
    raise ImportError("Missing langchain modules. Please install with: pip install langchain langchain-openai")
from pydantic import ValidationError

from prompts.llm_topic_questions import create_topic_questions_prompt, create_repair_prompt
from schemas.artifact import LLMTopicArtifact, JobResult
from worker.db import DatabaseManager, get_db_manager

logger = logging.getLogger(__name__)


class LLMWorkerRunner:
    """Main LLM worker for processing topic generation jobs."""
    
    def __init__(
        self,
        database_url: str,
        openai_api_key: str,
        openai_model: str = "gpt-4o-mini",
        max_retries: int = 1,
    ):
        """Initialize LLM worker.
        
        Args:
            database_url: PostgreSQL connection string
            openai_api_key: OpenAI API key
            openai_model: OpenAI model to use
            max_retries: Maximum number of repair retries for malformed JSON
        """
        self.db = get_db_manager(database_url)
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model
        self.max_retries = max_retries
        
        # Initialize LangChain ChatOpenAI
        self.llm = self._create_llm()
        
        logger.info(f"Initialized LLM worker with model: {openai_model}")
    
    def _create_llm(self) -> ChatOpenAI:
        """Create LangChain ChatOpenAI instance with proper configuration."""
        # Check if model supports JSON mode
        json_mode_models = {"gpt-4o-mini", "gpt-4o", "gpt-4-1106-preview", "gpt-3.5-turbo-1106"}
        supports_json_mode = any(model in self.openai_model for model in json_mode_models)
        
        model_kwargs = {}
        if supports_json_mode:
            model_kwargs["response_format"] = {"type": "json_object"}
        
        return ChatOpenAI(
            api_key=self.openai_api_key,
            model=self.openai_model,
            temperature=0,
            model_kwargs=model_kwargs,
        )
    
    async def process_single_job(self) -> JobResult | None:
        """Process a single job if available.
        
        Dispatches to appropriate handler based on job_type.
        
        Returns:
            JobResult if job was processed, None if no jobs available
        """
        start_time = time.time()
        
        # Claim next job
        job = await self.db.claim_next_job()
        if job is None:
            logger.debug("No jobs available for processing")
            return None
        
        job_id = str(job.id)
        job_type = getattr(job, "job_type", "topic_question_generation")  # Default to legacy type
        logger.info(f"Processing job {job_id} (type: {job_type}) for topic '{job.topic_slug}'")
        
        try:
            # Dispatch based on job type
            if job_type == "learning_material_generation":
                result = await self._process_learning_material_job(job, start_time)
            else:
                # Default to topic question generation (legacy behavior)
                result = await self._process_topic_generation_job(job, start_time)
            
            return result
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Job {job_id} failed: {error_msg}", exc_info=True)
            
            # Mark job as failed and emit event
            await self.db.mark_job_completed(job.id, "failed", error=error_msg)
            
            await self.db.emit_event("LLM_JOB_FAILED", {
                "job_id": job_id,
                "job_type": job_type,
                "topic_slug": job.topic_slug,
                "error": error_msg,
                "processing_time_ms": int((time.time() - start_time) * 1000),
            })
            
            processing_time_ms = int((time.time() - start_time) * 1000)
            
            return JobResult(
                job_id=job_id,
                status="failed",
                error_message=error_msg,
                processing_time_ms=processing_time_ms,
            )
    
    async def _process_learning_material_job(self, job: Any, start_time: float) -> JobResult:
        """Process a learning material generation job.
        
        Args:
            job: LLM job to process
            start_time: Job start timestamp
            
        Returns:
            JobResult with generation outcome
        """
        from worker.learning_material_handler import process_learning_material_generation
        
        job_id = str(job.id)
        logger.info(f"Generating learning material for job {job_id}")
        
        # Get database session for handler
        session = await self.db._get_session()
        
        try:
            # Call the learning material handler
            result = await process_learning_material_generation(
                job=job,
                session=session,
                llm_client=self.llm,
                max_retries=self.max_retries,
            )
            
            # Mark job as completed
            await self.db.mark_job_completed(
                job.id,
                "succeeded",
                result=result,
            )
            
            # Emit success event
            await self.db.emit_event("LEARNING_MATERIAL_GENERATED", {
                "job_id": job_id,
                "material_id": result.get("material_id"),
                "topic_slug": result.get("topic_slug"),
                "sections_count": result.get("sections_count"),
                "processing_time_ms": int((time.time() - start_time) * 1000),
            })
            
            processing_time_ms = int((time.time() - start_time) * 1000)
            
            return JobResult(
                job_id=job_id,
                status="succeeded",
                created_count=result.get("sections_count", 0),
                processing_time_ms=processing_time_ms,
            )
            
        except Exception as e:
            logger.error(f"Learning material generation failed for job {job_id}: {e}", exc_info=True)
            raise
    
    async def _process_topic_generation_job(self, job: Any, start_time: float) -> JobResult:
        """Process a legacy topic question generation job.
        
        Args:
            job: LLM job to process
            start_time: Job start timestamp
            
        Returns:
            JobResult with generation outcome
        """
        job_id = str(job.id)
        
        # Extract job parameters
        params = job.params or {}
        topic_slug = job.topic_slug
        topic_name = job.topic_name or topic_slug
        
        # Extract prompt parameters with defaults
        batch_size = params.get("batch_size", 10)
        language = params.get("language", "en")
        topic_hint_description = params.get("topic_hint_description", "")
        avoid_phrases = params.get("avoid_phrases", [])
        avoid_phrases_json = json.dumps(avoid_phrases)
        
        # Validate parameters
        if not topic_slug:
            raise ValueError("Job missing required topic_slug")
        
        if batch_size <= 0 or batch_size > 100:
            raise ValueError(f"Invalid batch_size: {batch_size} (must be 1-100)")
        
        # Generate content with LLM
        artifact = await self._generate_content(
            topic_slug=topic_slug,
            topic_display_name=topic_name,
            topic_hint_description=topic_hint_description,
            avoid_phrases_json=avoid_phrases_json,
            batch_size=batch_size,
            language=language,
        )
        
        # Process successful generation
        result = await self._process_successful_generation(job, artifact)
        
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        return JobResult(
            job_id=job_id,
            status="succeeded",
            created_count=result.created_count,
            topic_id=str(result.topic_id) if hasattr(result, "topic_id") else None,
            processing_time_ms=processing_time_ms,
        )
    
    async def _generate_content(
        self,
        topic_slug: str,
        topic_display_name: str,
        topic_hint_description: str,
        avoid_phrases_json: str,
        batch_size: int,
        language: str,
    ) -> LLMTopicArtifact:
        """Generate content using LLM with retry logic for malformed responses.
        
        Args:
            topic_slug: Topic identifier
            topic_display_name: Display name for topic
            topic_hint_description: Topic context/description
            avoid_phrases_json: JSON array of phrases to avoid
            batch_size: Number of questions to generate
            language: Language code
            
        Returns:
            Validated topic artifact
            
        Raises:
            Exception: If generation fails after retries
        """
        logger.info(f"Generating {batch_size} questions for topic '{topic_slug}'")
        
        # Create prompt messages
        messages = create_topic_questions_prompt(
            topic_slug=topic_slug,
            topic_display_name=topic_display_name,
            topic_hint_description=topic_hint_description,
            avoid_phrases_json=avoid_phrases_json,
            batch_size=batch_size,
            language=language,
        )
        
        # Initial generation attempt
        try:
            response = await self._call_llm(messages)
            return self._parse_and_validate_response(response)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning(f"Initial generation failed with parse error: {e}")
            
            # Attempt repair if we have retries left
            if self.max_retries > 0:
                return await self._attempt_repair(response, str(e))
            else:
                raise ValueError(f"Failed to parse LLM response: {e}") from e
    
    async def _call_llm(self, messages: list[BaseMessage]) -> str:
        """Call LLM with messages and return response text.
        
        Args:
            messages: Prompt messages for LLM
            
        Returns:
            Raw LLM response text
        """
        try:
            response = await self.llm.ainvoke(messages)
            return response.content.strip()
        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            raise ValueError(f"LLM API call failed: {e}") from e
    
    def _parse_and_validate_response(self, response: str) -> LLMTopicArtifact:
        """Parse and validate LLM response JSON.
        
        Args:
            response: Raw LLM response text
            
        Returns:
            Validated topic artifact
            
        Raises:
            json.JSONDecodeError: If JSON is malformed
            ValidationError: If JSON doesn't match schema
        """
        # Clean response (remove markdown if present)
        cleaned_response = response.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
        cleaned_response = cleaned_response.strip()
        
        # Parse JSON
        try:
            data = json.loads(cleaned_response)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            logger.error(f"Raw response: {response[:500]}...")
            raise
        
        # Validate with Pydantic
        try:
            artifact = LLMTopicArtifact(**data)
            logger.info(f"Successfully parsed artifact with {len(artifact.items)} questions")
            return artifact
        except ValidationError as e:
            logger.error(f"Validation error: {e}")
            logger.error(f"Parsed data: {json.dumps(data, indent=2)[:500]}...")
            raise
    
    async def _attempt_repair(self, original_response: str, error_message: str) -> LLMTopicArtifact:
        """Attempt to repair malformed LLM response.
        
        Args:
            original_response: Original malformed response
            error_message: Error from parsing attempt
            
        Returns:
            Validated topic artifact
            
        Raises:
            Exception: If repair fails
        """
        logger.info("Attempting to repair malformed LLM response")
        
        # Create repair prompt
        repair_prompt = create_repair_prompt(original_response, error_message)
        
        try:
            # Call LLM for repair
            from langchain.schema import HumanMessage
            repair_messages = [HumanMessage(content=repair_prompt)]
            repaired_response = await self._call_llm(repair_messages)
            
            # Try to parse repaired response
            return self._parse_and_validate_response(repaired_response)
            
        except Exception as e:
            logger.error(f"Repair attempt failed: {e}")
            raise ValueError(f"Failed to repair malformed response: {e}") from e
    
    async def _process_successful_generation(self, job, artifact: LLMTopicArtifact):
        """Process successful LLM generation by upserting data and updating job.
        
        Args:
            job: LLMJob instance
            artifact: Validated topic artifact
            
        Returns:
            UpsertResult with processing details
        """
        logger.info(f"Processing successful generation for job {job.id}")
        
        # Ensure topic exists
        topic_id = await self.db.ensure_topic(
            slug=artifact.topic.slug,
            name=artifact.topic.display_name,
            description=artifact.topic.description,
        )
        
        # Upsert questions
        upsert_result = await self.db.upsert_questions(topic_id, artifact.items)
        
        # Clean up pending topics
        await self.db.delete_pending_topic(artifact.topic.slug)
        
        # Mark job as succeeded
        await self.db.mark_job_completed(
            job.id,
            "succeeded",
            created_count=upsert_result.created_count,
        )
        
        # Emit success event
        await self.db.emit_event("LLM_JOB_SUCCEEDED", {
            "job_id": str(job.id),
            "topic_slug": artifact.topic.slug,
            "topic_id": str(topic_id),
            "questions_created": upsert_result.created_count,
            "questions_duplicated": upsert_result.duplicate_count,
            "total_questions": len(artifact.items),
        })
        
        logger.info(
            f"Job {job.id} completed successfully: "
            f"{upsert_result.created_count} questions created, "
            f"{upsert_result.duplicate_count} duplicates"
        )
        
        # Add topic_id to result for return value
        upsert_result.topic_id = topic_id
        return upsert_result
    
    async def process_jobs_loop(self, max_jobs: int = 10) -> list[JobResult]:
        """Process up to max_jobs in a loop.
        
        Args:
            max_jobs: Maximum number of jobs to process
            
        Returns:
            List of job results
        """
        logger.info(f"Starting job processing loop (max {max_jobs} jobs)")
        
        results = []
        for i in range(max_jobs):
            result = await self.process_single_job()
            if result is None:
                logger.info(f"No more jobs available after processing {i} jobs")
                break
            
            results.append(result)
            logger.info(f"Completed job {i+1}/{max_jobs}: {result.status}")
            
            # Brief pause between jobs
            await asyncio.sleep(0.1)
        
        logger.info(f"Job processing loop completed: {len(results)} jobs processed")
        return results
    
    async def cleanup(self) -> None:
        """Cleanup resources."""
        logger.info("Cleaning up LLM worker resources")
        await self.db.close()


def setup_logging(level: str = "INFO") -> None:
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    
    # Reduce noise from external libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_env_config() -> Dict[str, Any]:
    """Get configuration from environment variables."""
    config = {}
    
    # Required environment variables
    required_vars = ["OPENAI_API_KEY", "DATABASE_URL"]
    for var in required_vars:
        value = os.getenv(var)
        if not value:
            raise ValueError(f"Required environment variable {var} not set")
        config[var] = value
    
    # Optional environment variables with defaults
    config["OPENAI_MODEL"] = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    config["LOG_LEVEL"] = os.getenv("LOG_LEVEL", "INFO")
    config["MAX_JOBS"] = int(os.getenv("MAX_JOBS", "10"))
    
    return config


async def main() -> int:
    """Main entry point for worker runner."""
    parser = argparse.ArgumentParser(
        description="LLM worker for processing topic generation jobs"
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--once",
        action="store_true",
        help="Process a single job and exit (useful for testing)"
    )
    group.add_argument(
        "--loop",
        action="store_true", 
        help="Process up to N jobs per run (useful for batch processing)"
    )
    
    parser.add_argument(
        "--max-jobs",
        type=int,
        help="Maximum jobs to process in loop mode (overrides MAX_JOBS env var)"
    )
    
    args = parser.parse_args()
    
    try:
        # Load configuration
        config = get_env_config()
        
        # Setup logging
        setup_logging(config["LOG_LEVEL"])
        logger.info("Starting LLM worker runner")
        
        # Override max_jobs if provided via CLI
        if args.max_jobs:
            config["MAX_JOBS"] = args.max_jobs
        
        # Initialize worker
        worker = LLMWorkerRunner(
            database_url=config["DATABASE_URL"],
            openai_api_key=config["OPENAI_API_KEY"],
            openai_model=config["OPENAI_MODEL"],
        )
        
        try:
            if args.once:
                # Process single job
                logger.info("Processing single job")
                result = await worker.process_single_job()
                
                if result is None:
                    logger.info("No jobs available")
                    return 0
                else:
                    logger.info(f"Job completed with status: {result.status}")
                    return 0 if result.status == "succeeded" else 1
            
            elif args.loop:
                # Process multiple jobs
                logger.info(f"Processing up to {config['MAX_JOBS']} jobs")
                results = await worker.process_jobs_loop(config["MAX_JOBS"])
                
                if not results:
                    logger.info("No jobs available")
                    return 0
                
                # Check if any jobs failed
                failed_count = sum(1 for r in results if r.status == "failed")
                success_count = len(results) - failed_count
                
                logger.info(f"Processing complete: {success_count} succeeded, {failed_count} failed")
                return 0 if failed_count == 0 else 1
                
        finally:
            await worker.cleanup()
    
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down")
        return 130  # SIGINT exit code
    
    except Exception as e:
        logger.error(f"Worker runner failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
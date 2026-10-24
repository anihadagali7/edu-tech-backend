"""
Automatic worker trigger for LLM jobs.
Automatically processes jobs when created without manual worker execution.
"""
import asyncio
import logging
import os
from typing import Optional

from app.features.llm.worker import run_once

logger = logging.getLogger("llm.auto_worker")


class AutoWorker:
    """Automatic background worker that processes LLM jobs."""
    
    def __init__(self):
        self.is_processing = False
    
    async def trigger_job_processing(self, job_id: str = None):
        """
        Trigger automatic job processing.
        
        Args:
            job_id: Optional specific job ID to process (currently processes all queued)
        """
        if self.is_processing:
            logger.info("Worker already processing, skipping trigger")
            return
        
        try:
            self.is_processing = True
            logger.info(f"Auto-triggering worker for job {job_id or 'all queued jobs'}")
            
            # Process one job using the new worker
            count = await run_once(max_jobs=1)
            
            if count > 0:
                logger.info(f"Auto-worker completed {count} job(s)")
            else:
                logger.info("Auto-worker: no jobs available to process")
            
        except Exception as e:
            logger.error(f"Auto-worker processing failed: {e}", exc_info=True)
        finally:
            self.is_processing = False


# Global auto-worker instance
auto_worker = AutoWorker()


async def trigger_worker_async(job_id: str = None):
    """
    Async function to trigger worker processing.
    Can be called from endpoints as a background task.
    """
    await auto_worker.trigger_job_processing(job_id)

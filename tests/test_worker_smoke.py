"""Smoke tests for LLM worker functionality.

Tests the main worker components with mocked LLM responses to verify
job processing, deduplication logic, and database operations.
"""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


from app.features.llm.schema import LLMTopicArtifact, QuestionArtifact, TopicArtifact, QuestionExplanations, QuestionUpsertResult
from app.features.llm.worker import _compute_question_hash, _process_job, _claim_oldest_job, run_once
from worker.db import DatabaseManager
from worker.runner import LLMWorkerRunner

try:
    from langchain.schema import AIMessage
except ImportError:
    class AIMessage:
        def __init__(self, content):
            self.content = content


class TestWorkerSmoke:
    """Smoke tests for LLM worker functionality."""
    
    @pytest.fixture
    def mock_db_manager(self):
        """Create a mock database manager."""
        db_manager = MagicMock(spec=DatabaseManager)
        
        # Mock async methods
        db_manager.claim_next_job = AsyncMock()
        db_manager.ensure_topic = AsyncMock()
        db_manager.upsert_questions = AsyncMock()
        db_manager.mark_job_completed = AsyncMock()
        db_manager.emit_event = AsyncMock()
        db_manager.delete_pending_topic = AsyncMock()
        db_manager.close = AsyncMock()
        
        return db_manager
    
    @pytest.fixture
    def sample_job(self):
        """Create a sample LLM job."""
        job = MagicMock()
        job.id = uuid.uuid4()
        job.topic_slug = "linear-algebra"
        job.topic_name = "Linear Algebra"
        job.params = {
            "batch_size": 5,
            "language": "en",
            "topic_hint_description": "vectors, matrices, eigenvalues",
            "avoid_phrases": []
        }
        return job
    
    @pytest.fixture
    def sample_llm_response(self):
        """Create a sample LLM response JSON."""
        return {
            "topic": {
                "slug": "linear-algebra",
                "display_name": "Linear Algebra", 
                "description": "Linear algebra is the branch of mathematics concerning linear equations and their representations through matrices and vector spaces.",
                "tags": ["mathematics", "vectors", "matrices", "algebra", "calculus"]
            },
            "items": [
                {
                    "body": "What is the result of multiplying a 2x3 matrix by a 3x2 matrix?",
                    "choices": {
                        "A": "A 2x2 matrix",
                        "B": "A 3x3 matrix", 
                        "C": "A 2x3 matrix",
                        "D": "Multiplication is not possible"
                    },
                    "correct_answer": "A",
                    "difficulty": 2,
                    "explanations": {
                        "correct": "When multiplying matrices, the result has dimensions of the outer dimensions: (2x3) × (3x2) = 2x2 matrix.",
                        "distractors": {
                            "A": "",
                            "B": "This would be incorrect as it doesn't follow matrix multiplication rules.",
                            "C": "This keeps the first matrix dimensions, which is incorrect.",
                            "D": "Multiplication is possible when inner dimensions match."
                        }
                    },
                    "sources": ["Linear Algebra Textbook Ch. 3"]
                },
                {
                    "body": "What is the determinant of the identity matrix?",
                    "choices": {
                        "A": "0",
                        "B": "1",
                        "C": "-1", 
                        "D": "Undefined"
                    },
                    "correct_answer": "B",
                    "difficulty": 1,
                    "explanations": {
                        "correct": "The determinant of any identity matrix is always 1.",
                        "distractors": {
                            "A": "Zero is the determinant of singular matrices, not identity matrices.",
                            "B": "",
                            "C": "Negative one would indicate a reflection, not an identity transformation.",
                            "D": "The determinant is well-defined for identity matrices."
                        }
                    },
                    "sources": []
                }
            ]
        }
    
    @pytest.fixture
    def mock_llm_response_message(self, sample_llm_response):
        """Create a mock LLM response message."""
        return AIMessage(content=json.dumps(sample_llm_response))
    
    @pytest.mark.asyncio
    async def test_successful_job_processing(
        self, 
        mock_db_manager, 
        sample_job, 
        sample_llm_response,
        mock_llm_response_message
    ):
        """Test successful end-to-end job processing."""
        
        # Setup mocks
        mock_db_manager.claim_next_job.return_value = sample_job
        mock_db_manager.ensure_topic.return_value = uuid.uuid4()
        
        from schemas.artifact import QuestionUpsertResult
        mock_db_manager.upsert_questions.return_value = QuestionUpsertResult(
            created_count=2,
            duplicate_count=0,
            total_processed=2
        )
        
        # Create worker with mocked components
        with patch('worker.db.get_db_manager', return_value=mock_db_manager):
            with patch('worker.runner.ChatOpenAI') as mock_chat_openai:
                # Mock LLM response
                mock_llm_instance = AsyncMock()
                mock_llm_instance.ainvoke.return_value = mock_llm_response_message
                mock_chat_openai.return_value = mock_llm_instance
                
                worker = LLMWorkerRunner(
                    database_url="mock://test",
                    openai_api_key="test-key"
                )
                
                # Process job
                result = await worker.process_single_job()
                
                # Verify result
                assert result is not None
                assert result.status == "succeeded"
                assert result.created_count == 2
                assert result.job_id == str(sample_job.id)
                
                # Verify database calls
                mock_db_manager.claim_next_job.assert_called_once()
                mock_db_manager.ensure_topic.assert_called_once_with(
                    slug="linear-algebra",
                    name="Linear Algebra",
                    description="Linear algebra is the branch of mathematics concerning linear equations and their representations through matrices and vector spaces."
                )
                mock_db_manager.upsert_questions.assert_called_once()
                mock_db_manager.mark_job_completed.assert_called_once_with(
                    sample_job.id, "succeeded", created_count=2
                )
                mock_db_manager.emit_event.assert_called_once_with(
                    "LLM_JOB_SUCCEEDED",
                    {
                        "job_id": str(sample_job.id),
                        "topic_slug": "linear-algebra",
                        "topic_id": str(mock_db_manager.ensure_topic.return_value),
                        "questions_created": 2,
                        "questions_duplicated": 0,
                        "total_questions": 2
                    }
                )
    
    @pytest.mark.asyncio
    async def test_no_jobs_available(self, mock_db_manager):
        """Test behavior when no jobs are available."""
        
        # Setup: no jobs available
        mock_db_manager.claim_next_job.return_value = None
        
        with patch('worker.db.get_db_manager', return_value=mock_db_manager):
            worker = LLMWorkerRunner(
                database_url="mock://test",
                openai_api_key="test-key"
            )
            
            result = await worker.process_single_job()
            
            # Should return None when no jobs available
            assert result is None
            
            # Should only call claim_next_job
            mock_db_manager.claim_next_job.assert_called_once()
            mock_db_manager.ensure_topic.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_job_processing_with_llm_error(self, mock_db_manager, sample_job):
        """Test job processing when LLM call fails."""
        
        mock_db_manager.claim_next_job.return_value = sample_job
        
        with patch('worker.db.get_db_manager', return_value=mock_db_manager):
            with patch('worker.runner.ChatOpenAI') as mock_chat_openai:
                # Mock LLM to raise an exception
                mock_llm_instance = AsyncMock()
                mock_llm_instance.ainvoke.side_effect = Exception("API Error")
                mock_chat_openai.return_value = mock_llm_instance
                
                worker = LLMWorkerRunner(
                    database_url="mock://test",
                    openai_api_key="test-key"
                )
                
                result = await worker.process_single_job()
                
                # Verify failure handling
                assert result is not None
                assert result.status == "failed"
                assert "API Error" in result.error_message
                
                # Verify job was marked as failed
                mock_db_manager.mark_job_completed.assert_called_once()
                args = mock_db_manager.mark_job_completed.call_args[0]
                assert args[1] == "failed"  # status
                assert "API Error" in args[2]  # error message
                
                # Verify failure event was emitted
                mock_db_manager.emit_event.assert_called_once_with(
                    "LLM_JOB_FAILED",
                    {
                        "job_id": str(sample_job.id),
                        "topic_slug": sample_job.topic_slug,
                        "error": result.error_message,
                        "processing_time_ms": result.processing_time_ms
                    }
                )
    
    @pytest.mark.asyncio
    async def test_question_deduplication_logic(self, mock_db_manager):
        """Test question hash computation and deduplication."""
        
        with patch('worker.db.get_db_manager', return_value=mock_db_manager):
            worker = LLMWorkerRunner(
                database_url="mock://test", 
                openai_api_key="test-key"
            )
            
            topic_id = uuid.uuid4()
            
            # Test hash computation
            hash1 = worker.db.compute_question_hash(
                topic_id, 
                "What is 2 + 2?", 
                "A"
            )
            
            hash2 = worker.db.compute_question_hash(
                topic_id,
                "What is 2 + 2?",  # Same question
                "A"
            )
            
            hash3 = worker.db.compute_question_hash(
                topic_id,
                "What is 3 + 3?",  # Different question
                "A"
            )
            
            # Same question should produce same hash
            assert hash1 == hash2
            
            # Different question should produce different hash  
            assert hash1 != hash3
            
            # Hash should be deterministic and consistent length
            assert len(hash1) == 64  # SHA256 hex length
            assert all(c in '0123456789abcdef' for c in hash1)
    
    @pytest.mark.asyncio
    async def test_malformed_json_repair(self, mock_db_manager, sample_job):
        """Test repair mechanism for malformed JSON responses."""
        
        mock_db_manager.claim_next_job.return_value = sample_job
        
        # Malformed JSON (missing closing brace)
        malformed_json = '''
        {
            "topic": {
                "slug": "test-topic",
                "display_name": "Test Topic",
                "description": "Test description",
                "tags": ["test"]
            },
            "items": []
        '''  # Missing closing brace
        
        # Valid repaired JSON
        valid_json = {
            "topic": {
                "slug": "test-topic", 
                "display_name": "Test Topic",
                "description": "Test description for testing purposes only.",
                "tags": ["test"]
            },
            "items": [
                {
                    "body": "What is a test?",
                    "choices": {"A": "A", "B": "B", "C": "C", "D": "D"},
                    "correct_answer": "A",
                    "difficulty": 1,
                    "explanations": {
                        "correct": "A is correct",
                        "distractors": {"A": "", "B": "B is wrong", "C": "C is wrong", "D": "D is wrong"}
                    },
                    "sources": []
                }
            ]
        }
        
        with patch('worker.db.get_db_manager', return_value=mock_db_manager):
            with patch('worker.runner.ChatOpenAI') as mock_chat_openai:
                mock_llm_instance = AsyncMock()
                
                # First call returns malformed JSON, second call returns valid JSON
                mock_llm_instance.ainvoke.side_effect = [
                    AIMessage(content=malformed_json),  # Initial malformed response
                    AIMessage(content=json.dumps(valid_json))  # Repaired response
                ]
                mock_chat_openai.return_value = mock_llm_instance
                
                mock_db_manager.ensure_topic.return_value = uuid.uuid4()
                mock_db_manager.upsert_questions.return_value = QuestionUpsertResult(
                    created_count=1, duplicate_count=0, total_processed=1
                )
                
                worker = LLMWorkerRunner(
                    database_url="mock://test",
                    openai_api_key="test-key"
                )
                
                result = await worker.process_single_job()
                
                # Should succeed after repair
                assert result is not None
                assert result.status == "succeeded"
                
                # Should have made two LLM calls (original + repair)
                assert mock_llm_instance.ainvoke.call_count == 2
    
    def test_artifact_validation(self):
        """Test Pydantic validation of artifacts."""
        
        # Valid artifact
        valid_data = {
            "topic": {
                "slug": "test-topic",
                "display_name": "Test Topic", 
                "description": "This is a test topic for validation purposes.",
                "tags": ["test", "validation"]
            },
            "items": [
                {
                    "body": "What is the correct answer?",
                    "choices": {
                        "A": "Option A",
                        "B": "Option B", 
                        "C": "Option C",
                        "D": "Option D"
                    },
                    "correct_answer": "A",
                    "difficulty": 3,
                    "explanations": {
                        "correct": "A is the correct choice because...",
                        "distractors": {
                            "A": "",
                            "B": "B is incorrect because...",
                            "C": "C is incorrect because...",
                            "D": "D is incorrect because..."
                        }
                    },
                    "sources": ["Test Source"]
                }
            ]
        }
        
        # Should validate successfully
        artifact = LLMTopicArtifact(**valid_data)
        assert artifact.topic.slug == "test-topic"
        assert len(artifact.items) == 1
        assert artifact.items[0].correct_answer == "A"
        
        # Test invalid slug format
        invalid_slug_data = valid_data.copy()
        invalid_slug_data["topic"]["slug"] = "Invalid Slug!"  # Not kebab-case
        
        with pytest.raises(ValueError, match="kebab-case"):
            LLMTopicArtifact(**invalid_slug_data)
        
        # Test invalid correct_answer
        invalid_answer_data = valid_data.copy()
        invalid_answer_data["items"][0]["correct_answer"] = "E"  # Not A-D
        
        with pytest.raises(ValueError, match="correct_answer must be A, B, C, or D"):
            LLMTopicArtifact(**invalid_answer_data)
        
        # Test duplicate choices
        duplicate_choices_data = valid_data.copy()
        duplicate_choices_data["items"][0]["choices"]["B"] = "Option A"  # Duplicate of A
        
        with pytest.raises(ValueError, match="distinct"):
            LLMTopicArtifact(**duplicate_choices_data)


if __name__ == "__main__":
    # Run tests directly
    pytest.main([__file__, "-v"])
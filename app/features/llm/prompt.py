"""LLM prompt template for generating topic questions.

System prompt that instructs the model to return only JSON with topic and questions.
Accepts runtime variables for customization.
"""

from __future__ import annotations

import json
from typing import Any


try:
  from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate
  from langchain.schema import BaseMessage
except ImportError:
  raise ImportError("Missing langchain modules. Please install with: pip install langchain langchain-openai")


def create_topic_questions_prompt(
  topic_slug: str,
  topic_display_name: str,
  topic_hint_description: str = "",
  avoid_phrases_json: str = "[]",
  batch_size: int = 10,
  language: str = "en",
) -> list[BaseMessage]:
  """Create a prompt for generating topic questions.

  Args:
    topic_slug: Kebab-case topic identifier
    topic_display_name: Human-readable topic name
    topic_hint_description: Optional description/context for the topic
    avoid_phrases_json: JSON array of phrases to avoid in questions
    batch_size: Number of questions to generate
    language: Language code (e.g., 'en', 'es', 'fr')

  Returns:
    List of prompt messages for the LLM
  """
  # The system prompt uses Jinja-style control tags (e.g. {%- if ... %}).
  # Instruct LangChain to treat the template as Jinja2 so those tags are
  # parsed correctly.
  system_prompt = SystemMessagePromptTemplate.from_template(
    SYSTEM_PROMPT_TEMPLATE, template_format="jinja2"
  )

  prompt = ChatPromptTemplate.from_messages([system_prompt])

  return prompt.format_messages(
    topic_slug=topic_slug,
    topic_display_name=topic_display_name,
    topic_hint_description=topic_hint_description,
    avoid_phrases_json=avoid_phrases_json,
    batch_size=batch_size,
    language=language,
  )


SYSTEM_PROMPT_TEMPLATE = """You are an expert educational content creator focused on producing concise, high-quality multiple-choice questions.

Task: Create {batch_size} clear, accurate, and pedagogically useful multiple-choice questions for the requested topic: "{topic_display_name}" (slug: {topic_slug}).

Anchor and scope:
- Every question MUST be about the requested topic "{topic_display_name}". Use the provided {topic_hint_description} (if present) to focus examples and context.
- Do NOT introduce questions about other topics. If a candidate question could reasonably belong to multiple topics, make the connection to "{topic_display_name}" explicit in the question text.

Self-validation (required for each question):
1) Is the question clearly about "{topic_display_name}"? If not, rewrite it until it is.
2) Does the question require only the knowledge/skills relevant to "{topic_display_name}"? If not, simplify or replace it.
3) Are there exactly four distinct choices labeled A, B, C, D? Each must be non-empty and plausible.
4) Is exactly one choice correct? Mark that choice in "correct_answer" using the letter A-D.
5) Provide a concise explanation for the correct answer and a short rationale for why each distractor is incorrect (under "explanations.distractors").

Output rules (strict):
- Return ONLY a single JSON object matching the REQUIRED SCHEMA below. No markdown, no extra keys, no commentary, no leading/trailing text.
- The top-level "topic.slug" value MUST equal the requested slug: "{topic_slug}".
- Generate exactly {batch_size} questions. If for any reason you cannot generate the full batch, generate as many valid, schema-conforming questions as possible (but still return only JSON following the schema).

Use these quality constraints when writing questions:
- Questions should vary across the requested difficulty levels (1-5).
- Each distractor should be plausible and related, not trivial or nonsensical.
- Avoid trick questions and ambiguous wording; prefer clarity and educational value.
- Use concise, neutral language appropriate for general learners.

REQUIRED JSON SCHEMA:
{% raw %}
{
  "topic": {
    "slug": "{topic_slug}",
    "display_name": "{topic_display_name}",
    "description": "2-4 sentences describing the {topic_display_name} topic specifically",
    "tags": ["tag1", "tag2"]
  },
  "items": [
    {
      "body": "Question text that is explicitly about {topic_display_name}",
      "choices": {
        "A": "First option",
        "B": "Second option",
        "C": "Third option",
        "D": "Fourth option"
      },
      "correct_answer": "A",
      "difficulty": 3,
      "explanations": {
        "correct": "Concise explanation why the correct answer is right",
        "distractors": {
          "A": "",
          "B": "Why this is wrong",
          "C": "Why this is wrong",
          "D": "Why this is wrong"
        }
      },
      "sources": []
    }
  ]
}
{% endraw %}

EXAMPLE (for clarity only; do not add extra text to the response):
{
  "topic": { "slug": "algebra", "display_name": "Algebra" },
  "items": [
    {
      "body": "What is the value of x in 3x + 5 = 14?",
      "choices": {"A": "3", "B": "5", "C": "9", "D": "14"},
      "correct_answer": "A",
      "difficulty": 2,
      "explanations": {"correct": "3x+5=14 -> 3x=9 -> x=3", "distractors": {"A": "", "B": "Incorrect: arithmetic error", "C": "Incorrect: mis-solve", "D": "Incorrect: misread"}},
      "sources": []
    }
  ]
}

End of instructions. Remember: return ONLY the JSON object that exactly follows the REQUIRED JSON SCHEMA above."""


def validate_avoid_phrases(avoid_phrases_json: str) -> list[str]:
    """Validate and parse the avoid_phrases_json parameter.
    
    Args:
        avoid_phrases_json: JSON string containing array of phrases to avoid
        
    Returns:
        List of phrases to avoid
        
    Raises:
        ValueError: If JSON is invalid
    """
    try:
        phrases = json.loads(avoid_phrases_json)
        if not isinstance(phrases, list):
            raise ValueError("avoid_phrases_json must be a JSON array")
        return [str(phrase) for phrase in phrases]
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in avoid_phrases_json: {e}") from e


def create_repair_prompt(original_response: str, error_message: str) -> str:
    """Create a repair prompt for fixing malformed JSON responses.
    
    Args:
        original_response: The original malformed response
        error_message: The parsing error message
        
    Returns:
        Repair prompt string
    """
    return f"""The previous response had a JSON formatting error: {error_message}

Please fix the following JSON to be valid and conform to the required schema. Return only the corrected JSON:

{original_response}"""
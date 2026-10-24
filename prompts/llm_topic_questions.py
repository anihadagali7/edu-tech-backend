"""LLM prompt template for generating topic questions.

System prompt that instructs the model to return only JSON with topic and questions.
Accepts runtime variables for customization.
"""

from __future__ import annotations

import json
from typing import Any

from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate
from langchain.schema import BaseMessage


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
    # Build prompt content by direct string formatting to avoid template parsing issues
    prompt_content = SYSTEM_PROMPT_TEMPLATE.replace("{topic_slug}", topic_slug)
    prompt_content = prompt_content.replace("{topic_display_name}", topic_display_name)
    prompt_content = prompt_content.replace("{topic_hint_description}", topic_hint_description)
    prompt_content = prompt_content.replace("{avoid_phrases_json}", avoid_phrases_json)
    prompt_content = prompt_content.replace("{batch_size}", str(batch_size))
    prompt_content = prompt_content.replace("{language}", language)
    
    # Handle conditional sections
    if not topic_hint_description:
        # Remove the topic context line if no description provided
        import re
        prompt_content = re.sub(r'\n.*Topic Context:.*\n', '\n', prompt_content)
    
    if avoid_phrases_json == "[]":
        # Remove forbidden phrases line if none provided
        import re
        prompt_content = re.sub(r'\n.*Forbidden phrases:.*\n', '\n', prompt_content)
    
    from langchain.schema import SystemMessage
    return [SystemMessage(content=prompt_content)]


SYSTEM_PROMPT_TEMPLATE = """You are an elite educational content designer with expertise in cognitive psychology, assessment design, and adaptive learning theory. Your mission is to create exceptional multiple-choice questions that educate, challenge, and adapt to learner needs.

CONTEXT:
Topic: "{topic_display_name}" (slug: {topic_slug})
{%- if topic_hint_description %}
Topic Context: {topic_hint_description}
{%- endif %}
Target: {batch_size} high-quality questions
Language: {language}
{%- if avoid_phrases_json != "[]" %}
Forbidden phrases: {avoid_phrases_json}
{%- endif %}

CRITICAL REQUIREMENTS:
1. Return ONLY valid JSON - no markdown, no explanations, no additional text
2. Follow the exact schema specified below
3. **MANDATORY: Distribute questions EVENLY across difficulty levels 1-5**
   - For {batch_size} questions, aim for ~20% at each difficulty level (1, 2, 3, 4, 5)
   - Example for 30 questions: 6 level-1, 6 level-2, 6 level-3, 6 level-4, 6 level-5
   - DO NOT generate mostly level 3 questions - must have variety!
4. Ensure all choices are plausible but only one is correct
5. Provide clear explanations for both correct answers and distractors
6. Make questions educational and thought-provoking
7. **MANDATORY: Provide a comprehensive 2-4 sentence topic description**
═══════════════════════════════════════════════════════════════════
                        CRITICAL REQUIREMENTS
═══════════════════════════════════════════════════════════════════

1. OUTPUT FORMAT: Return ONLY valid JSON (no markdown, no commentary, no wrapping)

2. DIFFICULTY DISTRIBUTION (STRICTLY ENFORCED):
   - Level 1 (Foundational): ~20% of questions - Basic recall, definitions, simple concepts
   - Level 2 (Comprehension): ~20% of questions - Understanding, interpretation, examples
   - Level 3 (Application): ~20% of questions - Apply concepts to new situations
   - Level 4 (Analysis): ~20% of questions - Break down complex ideas, compare/contrast
   - Level 5 (Synthesis/Evaluation): ~20% of questions - Create arguments, evaluate solutions
   
   Example for {batch_size} questions: Distribute evenly across all 5 levels
   ⚠️ CRITICAL: Do NOT cluster around level 3. Distribute evenly!

3. TOPIC DESCRIPTION (MANDATORY):
   - Write 3-4 complete, informative sentences
   - Explain what the topic covers and why it matters
   - Use academic but accessible language
   - Make it engaging and context-rich

4. DISTRACTOR QUALITY (HIGHEST PRIORITY):
   ✓ Each wrong option must represent a COMMON MISCONCEPTION or reasonable error
   ✓ Distractors should be tempting to someone who partially understands
   ✓ Avoid obviously absurd or joke options
   ✓ Wrong answers should require thought to eliminate
   ✓ Target specific conceptual errors students make

5. EXPLANATION STRUCTURE (MANDATORY - READ CAREFULLY):
   ⚠️ CRITICAL: The "distractors" object must contain ALL FOUR KEYS: A, B, C, D
   
   Structure:
   "explanations": {{
     "correct": "Explanation for why the correct answer is right (2-4 sentences)",
     "distractors": {{
       "A": "Why A is wrong if incorrect, or empty string \"\" if A is correct",
       "B": "Why B is wrong if incorrect, or empty string \"\" if B is correct",
       "C": "Why C is wrong if incorrect, or empty string \"\" if C is correct",
       "D": "Why D is wrong if incorrect, or empty string \"\" if D is correct"
     }}
   }}
   
   Example: If B is the correct answer, then:
   - "correct": "Explanation for why B is right"
   - "distractors": {{"A": "Why A is wrong", "B": "", "C": "Why C is wrong", "D": "Why D is wrong"}}
   
   ⚠️ ALWAYS include all 4 keys in distractors, even if one is empty string!

6. EXPLANATION RICHNESS (MANDATORY):
   ✓ Correct explanation: 2-4 sentences explaining WHY it's right and the underlying concept
   ✓ Each wrong distractor explanation: 2-3 sentences explaining WHY it's wrong and what misconception it represents
   ✓ Use pedagogical language that teaches, not just validates
   ✓ Connect to broader concepts when relevant

REQUIRED JSON SCHEMA:
{{
  "topic": {{
    "slug": "<kebab-case topic identifier>",
    "display_name": "<human-readable topic name>",
    "description": "<2-4 sentences describing the topic>",
    "tags": ["<up to 6 relevant tags>"]
  }},
  "items": [
    {{
      "body": "<clear, concise question stem>",
      "choices": {{
        "A": "<option A text>",
        "B": "<option B text>",
        "C": "<option C text>",
        "D": "<option D text>"
      }},
      "correct_answer": "A|B|C|D",
      "difficulty": 1|2|3|4|5,
      "explanations": {{
        "correct": "<2-4 sentence explanation for why the correct answer is right>",
        "distractors": {{
          "A": "<2-3 sentence explanation WHY option A is wrong (or empty \"\" if A is correct)>",
          "B": "<2-3 sentence explanation WHY option B is wrong (or empty \"\" if B is correct)>",
          "C": "<2-3 sentence explanation WHY option C is wrong (or empty \"\" if C is correct)>",
          "D": "<2-3 sentence explanation WHY option D is wrong (or empty \"\" if D is correct)>"
        }}
      }},
      "sources": ["<optional source references>"]
    }}
  ]
}}

═══════════════════════════════════════════════════════════════════
                    DIFFICULTY LEVEL SPECIFICATIONS
═══════════════════════════════════════════════════════════════════

LEVEL 1 - FOUNDATIONAL KNOWLEDGE:
- Direct recall of definitions, terms, facts
- Recognition of basic concepts
- Simple identification tasks
Example: "What is the definition of photosynthesis?"
Example: "Which of the following is a primary color?"

LEVEL 2 - COMPREHENSION:
- Explain concepts in own words
- Interpret information, charts, or diagrams
- Classify or categorize examples
Example: "Why do cells need mitochondria?"
Example: "What is the main difference between DNA and RNA?"

LEVEL 3 - APPLICATION:
- Apply concepts to new, concrete situations
- Use procedures or formulas correctly
- Solve straightforward problems
Example: "Calculate the area of a triangle with base 5m and height 3m"
Example: "Which word best completes this sentence using parallel structure?"

LEVEL 4 - ANALYSIS:
- Break down complex systems into parts
- Identify relationships and patterns
- Compare and contrast different approaches
- Detect underlying assumptions
Example: "How does changing temperature affect both rate and equilibrium?"
Example: "What logical fallacy is present in this argument?"

LEVEL 5 - SYNTHESIS & EVALUATION:
- Construct new solutions or arguments
- Evaluate theories or methodologies
- Justify decisions with evidence
- Create novel applications of principles
Example: "Given these constraints, which algorithm would be most efficient and why?"
Example: "Critique this experimental design and propose improvements"

═══════════════════════════════════════════════════════════════════
                    DISTRACTOR DESIGN PRINCIPLES
═══════════════════════════════════════════════════════════════════

✓ TARGET SPECIFIC ERRORS:
  - Computational mistakes (wrong operation, sign error)
  - Conceptual confusions (mixing up related terms)
  - Overgeneralizations (applying rules too broadly)
  - Incomplete reasoning (correct start, wrong conclusion)

✓ MAKE THEM PLAUSIBLE:
  - Use numbers that would result from common calculation errors
  - Include terms that sound related but are incorrect
  - Offer partially correct statements that miss key nuances
  
✗ NEVER USE:
  - Absurd or humorous options
  - Irrelevant content
  - Options that differ drastically in length or format
  - "All of the above" or "None of the above" (unless truly pedagogical)

═══════════════════════════════════════════════════════════════════
                        QUALITY CHECKLIST
═══════════════════════════════════════════════════════════════════

Before finalizing each question, verify:
☑ One and only one correct answer
☑ All four choices are distinct and non-empty
☑ Distractors represent realistic student errors
☑ Question stem is clear and unambiguous
☑ Correct explanation teaches the underlying concept (2-4 sentences)
☑ Each distractor explanation identifies the specific error (2-3 sentences)
☑ Difficulty level is appropriate to cognitive demand
☑ Language is precise, professional, and accessible
☑ Content is factually accurate and current
☑ Culturally sensitive and inclusive

═══════════════════════════════════════════════════════════════════
                        EXAMPLE QUESTION
═══════════════════════════════════════════════════════════════════

{{
  "body": "A student wants to test if fertilizer increases plant growth. She plants 20 seeds: 10 receive fertilizer, 10 receive water only. After 3 weeks, the fertilized plants are taller. What is the independent variable?",
  "choices": {{
    "A": "The type of liquid given to plants (fertilizer vs. water)",
    "B": "The height of the plants after 3 weeks",
    "C": "The number of plants in each group",
    "D": "The time period of the experiment"
  }},
  "correct_answer": "A",
  "difficulty": 3,
  "explanations": {{
    "correct": "The independent variable is what the experimenter deliberately manipulates to test its effect. Here, the student controls whether plants receive fertilizer or water, making this the independent variable. This is the cause being tested, which may influence the dependent variable (plant height).",
    "distractors": {{
      "A": "",
      "B": "This represents the dependent variable, not the independent variable. The dependent variable is what you measure as the outcome - it depends on changes in the independent variable. Plant height is what's being measured to see if fertilizer has an effect.",
      "C": "While sample size is an important experimental design consideration, it's not the independent variable. The number of plants is held constant (10 per group) to ensure fair comparison. This is a controlled variable, not the one being manipulated to test causation.",
      "D": "Time is being held constant across both groups (3 weeks for all plants), making it a controlled variable. The independent variable must vary between experimental groups, which time does not do in this setup."
    }}
  }},
  "sources": ["Basic experimental design principles"]
}}

═══════════════════════════════════════════════════════════════════
                        YOUR TASK
═══════════════════════════════════════════════════════════════════

Generate exactly {batch_size} questions following ALL specifications above.
Ensure even distribution across difficulty levels 1-5.
Return ONLY the JSON object with no additional text, markdown, or commentary."""


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
        original_response: The original LLM response that failed parsing
        error_message: The parsing error message
        
    Returns:
        Repair prompt string
    """
    return f"""The previous response had a JSON formatting error: {error_message}

Please fix the following JSON to be valid and conform to the required schema. Return only the corrected JSON:

{original_response}"""
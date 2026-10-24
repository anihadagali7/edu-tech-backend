"""Prompt templates for generating comprehensive learning materials via LLM."""

from typing import Any


def create_learning_material_prompt(
    topic_name: str,
    topic_description: str | None = None,
    difficulty_level: str = "intermediate",
    target_audience: str = "high school to undergraduate students",
    additional_context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Generate a multi-turn prompt for creating detailed learning materials.
    
    The LLM will generate:
    1. A comprehensive overview
    2. Detailed sections covering key concepts
    3. Examples and explanations
    4. Practice problems (optional)
    5. Summary and key takeaways
    
    Args:
        topic_name: The topic to generate materials for (e.g., "Linear Algebra", "Fractions")
        topic_description: Optional additional context about what to cover
        difficulty_level: Target difficulty (beginner, intermediate, advanced)
        target_audience: Who the materials are for
        additional_context: Any extra requirements or specifications
        
    Returns:
        List of message dictionaries for the LLM conversation
    """
    
    context_str = ""
    if topic_description:
        context_str = f"\n\nAdditional Context: {topic_description}"
    
    extra_requirements = ""
    if additional_context:
        if additional_context.get("include_examples"):
            extra_requirements += "\n- Include worked examples for each major concept"
        if additional_context.get("include_practice"):
            extra_requirements += "\n- Include practice problems with solutions"
        if additional_context.get("visual_descriptions"):
            extra_requirements += "\n- Include descriptions of visual aids (diagrams, graphs) that would help understanding"
        if additional_context.get("real_world_applications"):
            extra_requirements += "\n- Include real-world applications and use cases"
    
    system_message = """You are an expert educational content creator specializing in creating comprehensive, 
well-structured learning materials. Your materials are:

1. **Pedagogically Sound**: You structure content from foundational concepts to advanced topics
2. **Clear and Accessible**: You use plain language while maintaining technical accuracy
3. **Example-Rich**: You provide concrete examples to illustrate abstract concepts
4. **Engaging**: You connect concepts to real-world applications
5. **Well-Organized**: You use clear headings, bullet points, and logical flow

You generate materials in JSON format with the following structure:
{
    "title": "Material Title",
    "summary": "Brief overview (2-3 sentences)",
    "sections": [
        {
            "title": "Section Title",
            "content_markdown": "Full markdown content for this section",
            "order": 0
        }
    ],
    "metadata": {
        "difficulty_level": "beginner|intermediate|advanced",
        "estimated_reading_time_minutes": 15,
        "prerequisites": ["topic1", "topic2"],
        "learning_objectives": ["objective1", "objective2"]
    }
}

IMPORTANT: Return ONLY valid JSON. Do not include markdown code blocks or any other formatting."""

    user_message = f"""Generate comprehensive learning materials for the following topic:

**Topic**: {topic_name}
**Difficulty Level**: {difficulty_level}
**Target Audience**: {target_audience}{context_str}

**Requirements**:
- Create 5-8 sections covering the topic thoroughly
- Each section should be 200-400 words
- Use clear markdown formatting (headings, lists, code blocks if applicable)
- Include mathematical notation where appropriate (use LaTeX-style $...$ for inline, $$...$$ for blocks)
- Start with foundational concepts and build to more advanced topics
- End with a summary section{extra_requirements}

**Content Guidelines**:
1. **Introduction Section**: Overview, why this topic matters, key concepts preview
2. **Foundation Sections**: Core concepts with clear definitions and explanations
3. **Application Sections**: How concepts work together, worked examples
4. **Advanced Topics** (if appropriate): More complex applications or extensions
5. **Summary Section**: Key takeaways, what we learned, next steps

Generate detailed, educational content that a student can learn from independently. Focus on clarity, 
comprehensiveness, and pedagogical effectiveness.

Return the result as valid JSON matching the schema above."""

    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


def create_material_expansion_prompt(
    existing_content: str,
    section_to_expand: str,
    expansion_request: str,
) -> list[dict[str, str]]:
    """Generate a prompt to expand or enhance a specific section of existing material.
    
    Args:
        existing_content: The current material content
        section_to_expand: Title of the section to expand
        expansion_request: What to add (e.g., "add more examples", "explain X in more detail")
        
    Returns:
        List of message dictionaries for the LLM conversation
    """
    
    system_message = """You are an expert educational content creator. You're enhancing existing learning 
materials by expanding specific sections with additional detail, examples, or clarifications.

Return your response as valid JSON with this structure:
{
    "expanded_content_markdown": "The enhanced section content in markdown",
    "additions_summary": "Brief description of what was added"
}

IMPORTANT: Return ONLY valid JSON."""

    user_message = f"""Enhance the following learning material section:

**Section to Expand**: {section_to_expand}

**Current Content**:
{existing_content}

**Enhancement Request**: {expansion_request}

Provide the expanded content that maintains the style and quality of the existing material while 
adding the requested improvements. Ensure smooth integration with surrounding content.

Return valid JSON with the expanded content."""

    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


def create_material_validation_prompt(material_json: str) -> list[dict[str, str]]:
    """Create a prompt to validate and potentially repair malformed learning material JSON.
    
    Args:
        material_json: The JSON string that may have formatting issues
        
    Returns:
        List of message dictionaries for validation/repair
    """
    
    system_message = """You are a JSON repair specialist. You receive potentially malformed JSON 
and return properly formatted, valid JSON.

The expected schema is:
{
    "title": "string",
    "summary": "string", 
    "sections": [
        {
            "title": "string",
            "content_markdown": "string",
            "order": number
        }
    ],
    "metadata": {
        "difficulty_level": "string",
        "estimated_reading_time_minutes": number,
        "prerequisites": ["string"],
        "learning_objectives": ["string"]
    }
}

IMPORTANT: Return ONLY valid JSON. Fix any syntax errors, escape special characters properly, 
and ensure all required fields are present."""

    user_message = f"""Fix and validate this learning material JSON:

{material_json}

Return the corrected JSON maintaining all content but fixing any formatting issues."""

    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]

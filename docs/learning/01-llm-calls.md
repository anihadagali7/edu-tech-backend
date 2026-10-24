# 1. Making LLM calls

Goal: understand exactly what happens when the app "asks Claude something", and be able to write that code yourself. All examples use the official `anthropic` Python SDK, which is what this app moves to in [revival-plan.md](../revival-plan.md) step 4.

## 1.1 The mental model

An LLM call is **one HTTP request** to `POST https://api.anthropic.com/v1/messages`. You send:

- `model`: which Claude to use, e.g. `claude-opus-5-5`
- `system`: standing instructions (persona, rules, output format)
- `messages`: the conversation so far, as a list of `{"role": "user" | "assistant", "content": ...}`
- `max_tokens`: the most text the reply may contain

You get back the reply as a list of content blocks (usually one `text` block), a `stop_reason` saying why it stopped, and `usage` (how many tokens you paid for).

Three facts that explain most surprises:

1. **The API is stateless.** Claude remembers nothing between calls. A "conversation" is just you sending the whole history every time. That is why the chatbot loads `study_messages` from Postgres before each call.
2. **You pay per token**, both in and out. A token is roughly ¾ of an English word. Opus 5.5 costs $4 per million input tokens and $20 per million output tokens.
3. **`max_tokens` cuts the reply off.** If `stop_reason == "max_tokens"`, the reply is incomplete. For JSON, that means broken JSON.

## 1.2 Your first call

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

```python
# scratch/hello.py
import anthropic

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

response = client.messages.create(
    model="claude-opus-5-5",
    max_tokens=1000,
    system="You write one multiple-choice question for a 10th grader.",
    messages=[{"role": "user", "content": "Topic: photosynthesis"}],
)

for block in response.content:
    if block.type == "text":
        print(block.text)

print(response.stop_reason)   # end_turn, max_tokens, refusal, ...
print(response.usage)         # input_tokens, output_tokens, cache_* tokens
```

Run it, then change the `system` text and watch the output change. The system prompt is the main lever you have.

## 1.3 Async, because FastAPI is async

Inside the API, always use the async client, so one slow LLM call never blocks other requests:

```python
client = anthropic.AsyncAnthropic()

response = await client.messages.create(model=..., max_tokens=..., messages=[...])
```

Create the client **once** (at module level), not per request. It holds a connection pool.

## 1.4 Streaming: text as it is written

The model writes the reply piece by piece. Streaming hands you each piece the moment it exists, so a chat UI can show words appearing instead of a 5-second blank.

```python
async with client.messages.stream(
    model="claude-opus-5-5",
    max_tokens=2000,
    messages=[{"role": "user", "content": "Explain photosynthesis to a 10 year old"}],
) as stream:
    async for text in stream.text_stream:
        print(text, end="", flush=True)
    final = await stream.get_final_message()   # full message + usage, after the stream ends
```

This is the single most visible fix for the chatbot. Today it waits for the whole reply and then fakes a stream ([04-chatbot.md](04-chatbot.md)).

Rule of thumb: stream anything a person watches, and anything with a large `max_tokens`. Long non-streamed requests can hit HTTP timeouts.

## 1.5 Structured output: guaranteed JSON

The question generator needs JSON that matches a schema. The old code asked nicely ("return ONLY JSON"), then stripped markdown fences, then fixed common mistakes. With structured output, the API **constrains** the reply to your schema:

```python
from app.features.llm.schema import TopicQuestionsArtifact   # a Pydantic model

response = await client.messages.parse(
    model="claude-opus-5-5",
    max_tokens=16000,
    system=QUESTION_SYSTEM_PROMPT,
    messages=[{"role": "user", "content": f"Topic: {name}. Write {n} questions."}],
    output_format=TopicQuestionsArtifact,
)
artifact = response.parsed_output        # already a validated TopicQuestionsArtifact
```

Without Pydantic, pass a raw JSON Schema with `client.messages.create(..., output_config={"format": {"type": "json_schema", "schema": {...}}})`.

## 1.6 Effort and thinking

Opus 5.5 always thinks a little before it answers. You set how much with `effort`:

```python
output_config={"effort": "low"}     # low | medium (default) | high | xhigh | max
```

- Tutor chat replies: `low`, for fast and cheap responses.
- Writing 20 good quiz questions with explanations: `high` is worth it.

Do **not** send `temperature`. It was the old knob for "creativity". The API now rejects it with a 400 error.

## 1.7 Prompt caching: pay less for repeated text

Every chat turn resends the same long system prompt. Caching stores that prefix on Anthropic's side for 5 minutes. Re-reading it then costs about 10% of the normal price.

```python
system=[{
    "type": "text",
    "text": TUTOR_SYSTEM_PROMPT,
    "cache_control": {"type": "ephemeral"},
}]
```

Caveats:

- It is a **prefix match**. Put fixed text first and changing text (timestamps, the learner's message) after.
- There is a minimum size. A short prompt (under about a thousand tokens) silently does not cache.
- Check that it works: `response.usage.cache_read_input_tokens` should be above 0 on the second call.

## 1.8 Errors and refusals

```python
try:
    response = await client.messages.create(...)
except anthropic.RateLimitError:        # 429: slow down; the SDK already retried twice
    ...
except anthropic.APIStatusError as e:   # other 4xx/5xx
    log.warning("claude_error", extra={"status": e.status_code})
except anthropic.APIConnectionError:    # network
    ...

if response.stop_reason == "refusal":
    # a safety classifier declined; read response.stop_details.category
    ...
```

The SDK already retries 429s, 5xx errors and connection errors 2 times with backoff, so the worker's `tenacity` wrapper becomes optional.

**Refusal fallbacks.** Opus 5.5 can decline a request through a safety classifier, though that is rare for a study app. If you opt in, the API retries a declined request on another model inside the same call:

```python
response = await client.beta.messages.create(
    model="claude-opus-5-5",
    max_tokens=16000,
    betas=["server-side-fallback-2026-07-01"],
    fallbacks="default",
    messages=[...],
)
```

This is a good default for the question worker. It is optional for chat.

## 1.9 Know what you spend

Log `response.usage` on every call. The worker already logs `duration_ms`, so add `input_tokens` and `output_tokens` next to it. To estimate cost before sending, use `client.messages.count_tokens(model=..., system=..., messages=...)`.

## Exercises

1. Run `hello.py`. Ask for a hard question, then an easy one, and compare `usage.output_tokens`.
2. Write `scratch/gen.py`. Call `messages.parse` with `TopicQuestionsArtifact` for "fractions", print `len(artifact.items)`, and print the difficulty spread.
3. Turn the same call into a stream. Print text as it arrives, and time the first token against the full reply.
4. Add `cache_control` to the system prompt, call twice, and print `cache_read_input_tokens`. If it is 0, the prompt is too short to cache.
5. Do revival-plan step 4.3: replace `provider_openai.py` with your `gen.py` code.

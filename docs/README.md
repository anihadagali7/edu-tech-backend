# EduTech docs

EduTech is an adaptive quiz platform. You pick a topic and answer multiple-choice questions. The difficulty goes up or down with your answers. An LLM writes the questions, and a tutor chatbot ("Study Buddy") gives hints.

Two repos:

| Repo | What it is | Hosted on |
|---|---|---|
| `edu-tech-ui` | Next.js 14 web app | Vercel |
| `edu-tech-backend` (this one) | FastAPI API, LLM worker, database migrations | Heroku |

## Start here

1. [architecture.md](architecture.md): how the pieces connect, with diagrams
2. [database.md](database.md): every table, with schema diagrams
3. [decisions.md](decisions.md): what we host where and why (the 2026 revival choices)
4. [revival-plan.md](revival-plan.md): what must be fixed before the first deploy, in order
5. [deployment.md](deployment.md): step-by-step setup of every account and deploy

## Features

- [Auth and roles](features/auth.md): Clerk login, how the API checks tokens, admin role
- [Adaptive quiz](features/adaptive-quiz.md): the difficulty rules and the live quiz stream
- [Topics and question generation](features/topic-generation.md): topic requests, admin approval, the LLM job worker
- [Study Buddy chatbot](features/study-buddy.md): the tutor chat, as it is built today
- [Admin panel](features/admin.md): users, topics, jobs, events

## Learning track: LLMs, agents, MCP

These guides use this app's own code as the running example.

1. [Making LLM calls](learning/01-llm-calls.md): one request, streaming, JSON output, caching, costs
2. [Tools and agents](learning/02-tools-and-agents.md): letting Claude call your functions
3. [MCP](learning/03-mcp.md): exposing this app as an MCP server and connecting Claude to MCP servers
4. [The chatbot, and how to improve it](learning/04-chatbot.md): what it does today, and a step-by-step upgrade plan

## Older design docs

[current_system_design.md](current_system_design.md) and [study_buddy_design.md](study_buddy_design.md) are the November 2025 design notes. They describe Supabase, OpenAI and AWS, which we no longer use. Where they disagree with the pages above, trust the pages above.

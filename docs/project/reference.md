# Project Reference

This document holds project reference material that is useful but too verbose for `AGENTS.md`.

## Overview

RpaClaw is a privacy-first personal research assistant powered by LangChain DeepAgents. It provides scientific tools, document generation, sandboxed code execution, and an RPA skill recording system. Data is intended to stay local.

For internal agents that need a problem-location route before changing code, start with `docs/project/agent-architecture-onboarding.md`.

## Tech Stack

- **Backend**: FastAPI, Python, Pydantic v2, Motor, LangGraph/DeepAgents.
- **Frontend**: Vue 3, TypeScript, Vite, Tailwind CSS, Reka UI.
- **Database**: MongoDB.
- **Cache/Queue**: Redis and Celery.
- **Sandbox**: Docker container with Xvfb, x11vnc, Playwright, Python.
- **Search**: SearXNG and Crawl4AI via websearch service.

## Directory Structure

```text
RpaClaw/
├── docker-compose.yml
├── docker-compose-release.yml
├── Skills/
├── Tools/
└── RpaClaw/
    ├── backend/
    │   ├── main.py
    │   ├── config.py
    │   ├── route/
    │   ├── deepagent/
    │   ├── rpa/
    │   ├── builtin_skills/
    │   ├── mongodb/
    │   └── im/
    ├── frontend/
    │   └── src/
    │       ├── main.ts
    │       ├── api/
    │       ├── pages/
    │       ├── components/
    │       ├── composables/
    │       ├── locales/
    │       └── utils/
    ├── sandbox/
    └── task-service/
```

## Services And Ports

| Service | Container Port | Common Host Port | Purpose |
|---------|----------------|------------------|---------|
| Frontend | 5173 | 5173 | Vue dev server / web UI |
| Backend | 8000 | 8000 or 12001 | FastAPI REST API |
| Sandbox | 8080 | 18080 | Code execution / noVNC |
| Sandbox VNC | 6080 | 16080 | Raw VNC websocket |
| MongoDB | 27017 | 27014 | Database |
| Task Service | 8001 | 12002 | Scheduled tasks |
| Websearch | 8068 | 8068 | SearXNG + Crawl4AI |

## Backend API

All routes are prefixed with `/api/v1`.

- `/auth`: login, register, password management.
- `/sessions`: session CRUD, skills listing, file operations.
- `/chat`: streaming chat with LLM agents.
- `/rpa`: RPA recording, testing, skill export.
- `/file`: file upload/download.
- `/models`: LLM model configuration.
- `/tools`, `/tooluniverse`: tool discovery.
- `/task-settings`: scheduled task configuration.
- `/im`: Feishu/Lark webhook integration.

Health check: `GET /health`

Readiness: `GET /ready`

## Frontend Routes

- `/chat`: main authenticated layout.
- `/`: home page.
- `/:sessionId`: chat conversation.
- `/skills`: skills browser.
- `/tools`: tools browser.
- `/tasks`: task scheduler.
- `/rpa/recorder`: RPA recording.
- `/rpa/configure`: configure recorded steps and parameters.
- `/rpa/test`: test generated Playwright script.
- `/share/:sessionId`: public session sharing.

## RPA Modes

- **Docker mode** (`STORAGE_BACKEND=docker`): Playwright runs in sandbox container, display is exposed through noVNC.
- **Local mode** (`STORAGE_BACKEND=local`): Playwright runs on host, CDP screencast is streamed to the frontend.

## Sandbox Interaction

Sandbox MCP uses JSON-RPC 2.0 at `SANDBOX_MCP_URL`.

- `sandbox_execute_bash`: parameter `cmd`; output is usually at `result.structuredContent.output`.
- `sandbox_execute_code`: parameters `code` and `language`; output is usually at `result.structuredContent.stdout`.

Supervisord manages sandbox browser services. Because browser services can have `autorestart=true`, prefer `supervisorctl stop/start` over `pkill`.

## Skill System

Skills are directories containing `SKILL.md` and implementation files.

```text
skill_name/
├── SKILL.md
└── skill.py
```

`SKILL.md` must include YAML front matter:

```markdown
---
name: example_skill
description: Example skill.
---
```

Skill directories:

- Built-in skills: `BUILTIN_SKILLS_DIR`.
- External skills: `EXTERNAL_SKILLS_DIR`.

The skills API scans both directories.

## Environment Variables

Important variables:

- `DS_API_KEY`, `DS_URL`, `DS_MODEL`: LLM config.
- `MONGODB_HOST`, `MONGODB_PORT`, `MONGODB_USER`, `MONGODB_PASSWORD`: database config.
- `SANDBOX_BASE_URL`, `SANDBOX_MCP_URL`: sandbox config.
- `STORAGE_BACKEND`: `local` for local desktop mode, otherwise sandbox mode.
- `RUNTIME_MODE`: relevant for non-local storage backend.
- `WEBSEARCH_BASE_URL`: websearch config.
- `EXTERNAL_SKILLS_DIR`, `BUILTIN_SKILLS_DIR`: skill paths.
- `TOOLS_DIR`: local desktop tool library path.
- `WORKSPACE_DIR`: workspace root.


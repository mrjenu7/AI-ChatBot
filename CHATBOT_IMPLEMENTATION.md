# We3vision Website Chatbot (PANDA)

PANDA is the We3vision business chatbot embedded in the Next.js website in `we3vision/`. The website UI calls a separate FastAPI service in `backend/`, which retrieves approved We3vision information from its local knowledge base and asks the configured LLM provider to draft a grounded answer.

## Is the chatbot portable?

**The chatbot is reusable, but it is not currently a standalone drop-in widget or an installable package.** Its UI and API are separated enough to move to another React/Next.js site, but the target site must also provide or adapt:

- The `AiChat` component and its supporting styles and `PandaMini` artwork component.
- A deployed FastAPI backend and a `NEXT_PUBLIC_CHATBOT_API_URL` pointing to it.
- Backend environment configuration, an LLM provider key, and the We3vision knowledge-base JSON file.
- CORS configuration allowing the target website origin.
- Website routes for any service links returned by the backend. These links are relative paths such as `/ai` and open on the current website domain.

The current backend CORS configuration supports one configured production website origin plus the listed local development origins. Supporting multiple production sites requires extending that allowlist. The frontend styling, branding, links, and data are We3vision-specific, so moving it to another brand requires adaptation.

## Repository layout

```text
backend/                         FastAPI chatbot API, RAG, LLM, and knowledge base
  app/api/routes/chat.py         Chat and dynamic service-catalog endpoints
  app/graph/nodes.py             Scope, response generation, and fallback behavior
  app/services/rag_service.py    Retrieval, service matching, context limits, links
  app/data/                      Knowledge-base JSON and PDF
we3vision/                       Next.js We3vision public site and chatbot UI
  src/components/site/ai-chat.tsx
  src/lib/ai-chat.ts
  src/app/globals.css            Chat panel styling
frontend/                        Separate legacy chatbot app; not the We3vision site
conv.txt                         Saved sample chatbot conversations
```

## Request and response flow

1. The website's `AiChat` component loads the service list from `GET /api/chat/services`.
2. The list is generated from backend knowledge-base records; the frontend does not keep its own hard-coded service catalogue.
3. With **All services**, the user question is matched against relevant service records. With one service selected, the selected service ID is sent as `selected_service_id` and narrows retrieval.
4. The website sends the question to `POST /api/chat`.
5. The backend checks scope, retrieves a bounded knowledge context, generates an English answer, and returns `service_links` found in the retrieved records.
6. The website renders those links as clickable relative paths. A path only works if that route exists on the deployed website.

Users may write in any language; chatbot answers are intended to be in English. The current website's `/api/chat` request sends the latest question rather than the full visible chat transcript. The backend stores turns when Supabase is configured, but this route initializes generation without prior chat history.

## Local development

Use two terminals from the repository root.

### 1. Start the backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

Create `backend/.env` using the environment variable names below. Do not commit API keys or service credentials.

### 2. Start the We3vision website

In `we3vision/.env.local`, set:

```dotenv
NEXT_PUBLIC_CHATBOT_API_URL=http://localhost:8000
```

Then run:

```powershell
cd we3vision
npm ci
npm run dev
```

Open `http://localhost:3000`. Set the backend's `FRONTEND_URL` to `http://localhost:3000` so browser requests pass CORS.

### 3. Check backend availability

- `GET http://localhost:8000/api/health`
- `GET http://localhost:8000/api/chat/services`
- `POST http://localhost:8000/api/chat`

Example request body:

```json
{
  "message": "Can We3vision help me build a website for my bakery?",
  "selected_service_id": null
}
```

For a focused service request, pass an `id` returned by `/api/chat/services` as `selected_service_id`.

## Environment variables

### Backend (`backend/.env`)

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Provider API key. The current default provider is Groq; keep this key server-side only. |
| `OPENAI_BASE_URL` | OpenAI-compatible API base URL; current default is `https://api.groq.com/openai/v1`. |
| `LLM_MODEL` | Provider model ID; current default is `openai/gpt-oss-120b`. |
| `LLM_TEMPERATURE` | Response-generation temperature. |
| `LLM_MAX_TOKENS` | Configured output cap; generation code currently applies a hard maximum of 300 tokens. |
| `FRONTEND_URL` | Allowed website origin for CORS, e.g. `http://localhost:3000` or the production origin. |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | Optional conversation storage credentials. Keep the service key private. |
| `GOOGLE_SHEET_ID`, `GOOGLE_WORKSHEET_NAME`, `GOOGLE_SERVICE_ACCOUNT_FILE` | Optional/legacy spreadsheet configuration. |
| `APP_TIMEZONE` | Backend timezone setting. |

The knowledge base is read from `backend/data/we3vision_knowledge_base.json`; keep this file available in the backend deployment. The PDF is a fallback source when supported dependencies are installed.

### Website (`we3vision/.env.local` or hosting environment)

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_CHATBOT_API_URL` | Public base URL of the deployed FastAPI backend, without `/api/chat`. |

The `NEXT_PUBLIC_` variable is included in browser-side website code. It must contain only the API base URL, never an API key.

## Implemented chatbot behavior

- Dynamic service combobox populated by the backend knowledge base.
- Selected service ID is validated by the backend and used to focus retrieval.
- In **All services**, service-intent aliases help match questions (including common Roman Gujarati/Hindi phrases) to the relevant service record.
- Retrieved service records can produce clickable service links in the assistant response.
- Company-only scope handling; unrelated requests are declined.
- Evidence-grounded answers: unverified capabilities and unsupported guarantees should not be presented as confirmed.
- English-only answers while accepting multilingual input.
- A temporary provider failure returns: "Sorry, the AI service is temporarily unavailable. Please try again in a moment."
- The chat panel is taller than its initial layout; the service dropdown has a constrained scroll area, and wheel movement inside chat messages is kept in the chat panel.
- User message limit: 1,000 characters at the API boundary.

## Token and rate-limit safeguards

The current backend changes reduce request size:

- Default system prompt is shortened to about 900 characters.
- Retrieved RAG context is capped at 3,200 characters.
- Response generation is capped at 300 output tokens even if `LLM_MAX_TOKENS` is configured higher.
- The streaming API keeps at most two recent turns and 1,200 history characters; selected-service requests omit prior history.

These measures reduce tokens per request and help avoid oversized requests such as the earlier 8,743-token request. They **do not guarantee service for 1,000 simultaneous users**. Provider rate limits are shared at the provider organization level, and this repository does not currently include a distributed request queue, shared rate limiter, automatic second-provider failover, or a load-test result. Before a large live test, verify the production organization's actual RPM/TPM capacity, configure adequate provider capacity, and run a load test against the deployed backend. The fallback keeps the chat UI usable when generation fails; it does not generate an AI answer during provider downtime.

## Deployment checklist

1. Deploy `backend/` as a reachable FastAPI service and include `backend/data/we3vision_knowledge_base.json`.
2. Configure `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL`, and production `FRONTEND_URL` on the backend host.
3. Configure `NEXT_PUBLIC_CHATBOT_API_URL` to the public backend URL in the Next.js build/deployment environment.
4. Confirm the production site's origin is allowed by backend CORS.
5. Check service links against actual production website routes to avoid 404s.
6. Verify provider capacity for expected test traffic. Horizontal scaling of the website/backend alone does not raise a shared LLM provider quota.
7. Check `GET /api/health`, load the service dropdown, send an `All services` question, and test one selected service before opening the site to users.

## Basic verification commands

Backend Python syntax check:

```powershell
cd backend
python -m py_compile app/core/config.py app/graph/nodes.py app/services/rag_service.py app/api/routes/chat.py app/services/llm_service.py
```

Website TypeScript check:

```powershell
cd we3vision
npm run typecheck
```


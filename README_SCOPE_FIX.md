# We3vision chatbot: scope classification correction

This supersedes the previous company-guard patch, which overused AMBIGUOUS and repeatedly asked whether the user meant We3vision.

## Fixes
- Clear official We3vision and service enquiries go to RAG immediately; no separate classifier call.
- Lookalike brands and named unrelated companies are declined.
- Greetings are allowed.
- Ordinary follow-up messages can use recent conversation context.
- Truly unclear messages alone can trigger a clarification. Failure of the AI classifier is not mistaken for evidence that a clear company question is ambiguous.
- Both `/chat` (LangGraph) and `/chat/stream` load history before the shared scope gate; `llm_service.generate_reply` also uses the updated scope gate.

## Installation
**Complete source:** extract the full-source ZIP to a fresh folder. Restore your own `backend/.env` and private Google service-account JSON from your existing project. Those secrets are intentionally excluded. Set up your environment using your existing package installation instructions.

**Patch only:** copy the patch's `backend/app/...` files over the corresponding files in your current project. Restart FastAPI so its Python modules reload. No knowledge-base rebuild is required for this issue.

## Offline regression tests
From project root, with backend Python dependencies installed:

    PYTHONPATH=backend python -m unittest backend/tests/test_company_guard.py -v

Windows PowerShell:

    $env:PYTHONPATH="backend"; python -m unittest backend/tests/test_company_guard.py -v

## Important limits
Unknown names and nuanced mixed-company questions may need the configured online classifier. The fallback declines uncertain requests rather than fabricating company facts. Follow-up classification trusts conversation history: do not use untrusted histories from other users. Test your configured LLM separately for live answers, since the included tests don't contact your provider.

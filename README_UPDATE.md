# We3vision chatbot — company scope guard update

## What changed

- **New:** `backend/app/services/company_guard.py`: deterministic rejection for lookalike brands (`Wepro Vision`, `Weprovision`, `We4vision`, etc.) plus a lightweight LLM-based scope classifier for unrelated companies/topics, greetings, and potential client enquiries.
- **Updated:** `backend/app/graph/workflow.py`, `nodes.py`, `state.py`: scope validation runs before RAG or response generation, and refusals are saved in conversation history.
- **Updated:** `backend/app/api/routes/chat.py`: `/chat/stream` uses the same guard and returns a normal NDJSON `meta`, `delta`, `done` sequence when declining.
- **Updated:** `backend/app/services/llm_service.py`: the compatibility `generate_reply()` entry point also checks scope.
- **Tests:** `tests/test_company_guard.py` (offline tests; no real API calls).

## Install

For the full updated project archive, extract it into a **new** directory and copy your existing local `.env` and private Google service-account file into their original locations. Those secrets are deliberately **not included** in the updated archive. Keep your existing dependency setup or reinstall using the existing requirements and frontend package-lock files.

For the smaller patch archive, merge its `backend/app/...` files into the equivalent paths in your existing project. Do not overwrite `.env`, credentials, or unrelated files.

## Run tests

From the project root:

```bash
python -m unittest discover -s tests -v
```

## Behavior

- `Tell me about Wepro Vision` => direct refusal, without any model call.
- `Tell me about We3vision` => company scope classifier, then RAG + regular answer.
- `Tell me about Google` => scope classifier normally declines.
- `Can you develop a website?` => scope classifier should allow a business enquiry.
- `Hello` => greeting allowed.

**Notes:** A configured, available model is needed to classify queries beyond obvious lookalike brands and greetings; on classifier failure the chatbot asks the user to clarify rather than answering potentially out-of-scope content. Classification introduces one short extra LLM request for most conversations. A classifier can make mistakes; test with your real provider before production deployment. When users mention We3vision and another company together, the classifier makes the scope decision rather than blindly accepting the mention of We3vision.

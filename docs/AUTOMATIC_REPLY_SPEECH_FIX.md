# Automatic AI reply speech

This build automatically speaks every AI reply after it appears in the chat.

## Expected behavior

1. Open Webot.
2. Ask a question by clicking Send or pressing Enter.
3. The text answer appears.
4. Webot immediately starts speaking the same answer.
5. Gujarati answers use Gujarati TTS, Hindi answers use Hindi TTS, and English answers use English TTS.

The header speaker icon controls this behavior:

- Speaker ON: every new AI answer is spoken automatically.
- Speaker OFF: answers remain silent; the per-message play button can be used after re-enabling voice.

## Why this change was needed

The earlier code already called TTS after receiving an answer, but browser audio playback can be blocked when audio is started only after an asynchronous API request. This build primes/unlocks audio during the user's real click or Enter key action, then reuses that audio channel when the response arrives.

## Files changed

- `frontend/src/components/chatbot/Chatbot.jsx`

No RAG, same-language response, LLM, knowledge-base, or multilingual voice-selection logic was removed.

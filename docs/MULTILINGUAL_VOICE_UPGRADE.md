# Multilingual response + natural voice upgrade

This beta update follows the relevant items in **We3vision AI Business Agent Project Track**:

- **3.13 Multilingual Conversation** — latest-message language detection and same-language response enforcement.
- **2.16 TTS Playback Control** — assistant replies use the backend neural TTS first and browser TTS as a fallback.
- **4.27 TTS Service / 4.28 Voice API** — FastAPI now exposes `POST /api/voice/tts`.

## Why the Gujarati screenshot returned English

The old frontend did this:

1. Call `/api/chat`.
2. If the API call failed for any reason, silently run `getBotResponse()`.
3. `getBotResponse()` contained only English career-guidance templates.

That English fallback has been removed. A backend/network problem can no longer become a fake English AI answer.

## Language contract

The backend now detects the **latest user message** before generating an answer. Gujarati/Hindi native scripts receive hard language rules. If the model still returns the wrong script, the backend performs one language-repair pass before returning the answer.

Examples:

- `તમારી કંપની શું કામ કરે છે?` → Gujarati-script answer.
- `आपकी कंपनी क्या करती है?` → Hindi-script answer.
- `What services do you provide?` → English answer.
- `tame shu service aapo cho?` → Gujarati in Latin/Gujlish style.
- `aap kya service dete hain?` → Hindi in Latin/Hinglish style.

For other languages, `langid` provides a broad language hint and the LLM is told to preserve that language.

## Voice

The frontend requests neural audio from `POST /api/voice/tts`. Preferred voices are configured for Hindi, Gujarati and Indian English. Other languages are resolved from the available neural voice catalogue when possible. If neural TTS is unavailable, the frontend falls back to the browser speech engine with the matching locale instead of forcing an English voice.

Hindi/Gujarati speech is slightly slowed to improve word boundaries and clarity.

## Run

Backend:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

Frontend in a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Test the exact screenshot question:

```text
તમારી કંપની શું કામ કરે છે અને તમારી મુખ્ય સેવાઓ કઈ છે?
```

The API response now also returns `language` and `locale`, which the frontend passes to TTS.

## Automatic reply speech fix (v2.1)

The chatbot now starts speaking each assistant reply automatically as soon as the reply is received and rendered. The user does not need to click the small play button on every message.

Changes in `frontend/src/components/chatbot/Chatbot.jsx`:

- Automatic TTS is enabled by default through the existing speaker toggle.
- Browser audio is primed during the user's click/Enter gesture so asynchronous reply audio is not silently blocked by browser autoplay rules.
- Neural TTS starts immediately after the API answer instead of waiting for a delayed timer.
- The same persistent audio player is reused for replies.
- Stale TTS requests are cancelled when a new question is sent.
- Neural TTS still falls back to browser speech if `/api/voice/tts` cannot generate or play audio.
- Browser fallback is chunked so longer replies are spoken more reliably.
- Gujarati/Hindi language and voice selection from the multilingual upgrade are preserved.

The speaker icon in the chatbot header now means **Automatic voice ON/OFF**. Keep it ON when every AI response should be spoken automatically.

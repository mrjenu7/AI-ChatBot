# Webot robot integrated into your current pr-10 project

This project uses your uploaded `pr-10.zip` as its base. Aria has been replaced with the same Webot robot artwork and 2D animation code from `Webot_Chatbot_Complete.zip`.

## Robot behavior

- Opens with the same entrance from the left.
- Uses the previous Webot idle and thinking motion.
- Moves its body, head and hands while the existing speech player speaks.
- Keeps a fixed smile: no lip-sync.
- Waves goodbye for **1.3 seconds** before the existing Close action dismisses the window.
- Reopening keeps the current conversation and replays the entrance.

The current project's chat layout, input, history, voice controls and minimize/restore controls are retained. No new controls were added to the main chatbot. The current API calls, speech services, backend, RAG, Google Sheets integration and configuration are unchanged.

## Run on Windows

Use Python 3.11 or 3.12 and Node.js 22.12 or newer. Extract the ZIP and open two PowerShell terminals inside `Webot_Chatbot_pr10`.

Your uploaded `.env` files and Google service-account file are retained. Keep your working settings.

Terminal 1:

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

If you already have a working virtual environment, use its Python executable and your existing start command.

Terminal 2:

```powershell
cd frontend
npm ci
npm run dev
```

Open **http://localhost:5173** and click **Ask Webot**.

On macOS/Linux, use `python3 -m venv .venv` and `.venv/bin/python` instead of the Windows Python paths. The npm commands are the same.

## Optional robot preview

Open **http://localhost:5173/avatar-preview.html** while the frontend is running. This independent preview from the previous Webot project includes entrance, voice samples in English/Hindi/Gujarati, and the goodbye wave. The preview has its own demonstration controls; the main chatbot retains your current project's controls.

The included production build is in `frontend/dist`. To preview it without installing npm dependencies, run `python -m http.server 5173 --directory frontend/dist` from the project folder. The complete AI conversation still needs the backend.

## Verification

- Frontend production build passed.
- **12 automated frontend tests passed.**
- All **31 backend files** are byte-for-byte identical to the uploaded project.
- The frontend API client, voice services, speech hook, website shell, dependency manifests and configuration are unchanged.
- Chat input and existing voice/history handlers were compared with the uploaded source and are preserved.
- Robot artwork, motion code, shaders and component match the previous Webot ZIP byte-for-byte.

Interactive browser verification and live AI/Google Sheets checks were not completed here. See `docs/WEBOT_VERIFICATION.json` for the scope of the checks.

Dependency folders and local caches are omitted; installation recreates them.

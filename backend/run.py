"""Local dev server entrypoint (Windows-safe).

Windows' default event loop has a known DNS resolution quirk with certain
hostnames. The fix is switching to the Selector event loop policy -- but
that has to happen *before* uvicorn creates its event loop, which is too
late if set inside app/main.py (uvicorn's --reload mode imports the app
from inside an already-running loop, in a subprocess). Running uvicorn
programmatically from here, without --reload, guarantees the policy is
set first.

Use this for local development on Windows: `uv run python run.py`
Everywhere else (Mac/Linux, and production later), the normal
`uvicorn app.main:app --reload` command is fine as-is.
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)

#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, "/workspace")
from app.backend.config import settings

os.environ["OPENAI_API_KEY"] = settings.openai_api_key
os.environ["OPENAI_BASE_URL"] = settings.openai_base_url

print(f"DEBUG: OPENAI_API_KEY={settings.openai_api_key[:20]}...")

import uvicorn
if __name__ == "__main__":
    uvicorn.run("app.backend.main:app", host="0.0.0.0", port=8000, reload=True)

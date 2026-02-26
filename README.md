# LinkedIn Mutual Connections Agent

LLM-driven browser agent that logs into LinkedIn via saved session cookies and extracts all mutual connections from any profile — returning structured JSON with name, LinkedIn URL, title, and location.

**Stack:** [browser-use](https://browser-use.com) · Playwright · Gemini (`gemini-3-flash-preview`) · Python 3.11+

---

## Setup

### 1. Install uv (if not already)
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Clone & install dependencies
```bash
git clone https://github.com/Peaceout21/linkedin-mutual-connections
cd linkedin-mutual-connections

uv venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

uv pip install -e .
playwright install chromium
```

### 3. Add your Gemini API key
```bash
cp .env.example .env
# edit .env and add your GOOGLE_API_KEY
```

Get a free key at [aistudio.google.com](https://aistudio.google.com/apikey).

### 4. Save your LinkedIn session cookies
```bash
python save_cookies.py
```
A browser window opens — log into LinkedIn, then press Enter. Saves `linkedin_storage.json` (git-ignored).

### 5. Run
```bash
python mutual_connections.py \
  --url "https://www.linkedin.com/in/someprofile/" \
  --save results.json
```

---

## Output format

```json
{
  "target_profile": "https://www.linkedin.com/in/someprofile/",
  "mutual_count": 21,
  "extracted_at": "2026-02-26T11:35:56Z",
  "mutual_connections": [
    {
      "name": "Full Name",
      "linkedin_url": "https://www.linkedin.com/in/username",
      "linkedin_id": "username",
      "title": "Their current role",
      "location": "City, Country"
    }
  ]
}
```

---

## Notes

- `linkedin_storage.json` and `.env` are git-ignored — never committed.
- If LinkedIn redirects to login, re-run `save_cookies.py` to refresh the session.
- To extract more connections, increase `max_steps=40` in `mutual_connections.py`.

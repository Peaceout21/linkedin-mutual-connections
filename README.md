# LinkedIn Agent Toolkit

LLM-driven browser agents that log into LinkedIn via saved session cookies and extract structured data — returning clean JSON ready for CRM use.

**Scripts:**
- `mutual_connections.py` — extract all mutual connections from any LinkedIn profile
- `company_people.py` — extract all **2nd-degree connections** from a company's `/people/` tab

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

**Mutual connections from a profile:**
```bash
python mutual_connections.py \
  --url "https://www.linkedin.com/in/someprofile/" \
  --save results.json

# Optional: also fetch latest experience entry for each mutual
python mutual_connections.py \
  --url "https://www.linkedin.com/in/someprofile/" \
  --save results.json \
  --enrich
```

**2nd-degree connections from a company:**
```bash
python company_people.py \
  --url "https://www.linkedin.com/company/acme/" \
  --save out.json

# For large companies (200+ employees):
python company_people.py \
  --url "https://www.linkedin.com/company/acme/" \
  --save out.json \
  --max-steps 120
```

---

## Output format

### `mutual_connections.py`
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
      "title": "Their headline",
      "company": "Current company or null",
      "location": "City, Country"
    }
  ]
}
```

### `company_people.py`
Returns only **2nd-degree** employees, with CRM metadata fields pre-populated:
```json
{
  "meta": {
    "company_url": "https://www.linkedin.com/company/acme",
    "company_name": "Acme Corp",
    "people_tab_url": "https://www.linkedin.com/company/acme/people/",
    "extracted_at": "2026-02-27T10:00:00Z",
    "total_employees_visible": 45,
    "second_degree_count": 12
  },
  "people": [
    {
      "name": "Jane Doe",
      "linkedin_url": "https://www.linkedin.com/in/janedoe",
      "linkedin_id": "janedoe",
      "title": "Partner",
      "location": "New York, NY",
      "connection_degree": "2nd",
      "tags": [],
      "notes": "",
      "contacted": false,
      "contact_date": null
    }
  ]
}
```

---

## Notes

- `linkedin_storage.json` and `.env` are git-ignored — never committed.
- If LinkedIn redirects to login, re-run `save_cookies.py` to refresh the session.
- To extract more connections, increase `max_steps` (`mutual_connections.py`: default 40, `company_people.py`: default 80).

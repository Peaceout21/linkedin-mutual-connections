# LinkedIn Agent Toolkit

LLM-driven browser agents that log into LinkedIn via saved session cookies and extract structured data — returning clean JSON ready for CRM use.

**Scrapers:**
- `mutual_connections.py` — extract all mutual connections from any LinkedIn profile
- `company_people.py` — extract all visible connections (2nd-degree + public 3rd+) from a company's `/people/` tab

**Stack:** [browser-use](https://browser-use.com) · Playwright · Gemini (`gemini-3-flash-preview`) · Python 3.11+ · FastAPI · GCP (Pub/Sub · Firestore · Cloud Run)

---

## Architecture

```
Frontend / API caller
      ↓  POST /jobs  (Cloud Run — permanent public URL)
Cloud Run API
      ↓  publishes message
   Pub/Sub topic: linkedin-jobs
      ↓  pulled by whichever Mac is online
Local worker (runs on team Macs via launchd)
      ↓  runs browser scrape
   Firestore — job status + 90-day result cache
```

- **Cloud Run** is the only public-facing piece. It accepts job requests and queues them — no browser, no scraper runs there.
- **Workers** (team Macs) poll Pub/Sub outbound every 30s. No public URL needed — they dial out, nothing dials in.
- **Pub/Sub** guarantees exactly one Mac gets each job. If all Macs are offline, jobs wait up to 7 days.
- **Dead letter queue** (`linkedin-jobs-dead`): after 5 failed attempts a job is marked `dead` in Firestore and a Slack alert is sent.

### Job types

| `job_type` | Input URL | What it scrapes |
|---|---|---|
| `mutual_connections` | `/in/username` | All mutual connections with a person |
| `company_people` | `/company/slug` | All visible employees on a company page |

### Job lifecycle

```
pending → running → completed
                 ↘ failed (retried by Pub/Sub, up to 5×)
                 ↘ dead (after 5 failures → DLQ + Slack alert)
```

### Live infrastructure

| Component | Value |
|---|---|
| Cloud Run API | `https://linkedin-api-461238503904.us-central1.run.app` |
| GCP project | `chromatic-being-375320` |
| Firestore database | `linkedin-api` |
| Pub/Sub topic | `linkedin-jobs` |
| Pub/Sub subscription | `linkedin-jobs-local` |
| Dead letter topic | `linkedin-jobs-dead` |
| Dead letter subscription | `linkedin-jobs-dead-sub` |

---

## New contributor setup

```bash
git clone https://github.com/Peaceout21/linkedin-mutual-connections
cd linkedin-mutual-connections
bash setup.sh
```

`setup.sh` handles everything:
1. Python 3.11+ check
2. Creates `venv` + installs all dependencies
3. Installs Playwright Chromium
4. Creates `.env` from `.env.example` and prompts for your `WORKER_NAME`
5. Checks gcloud ADC — tells you exactly what to run if missing
6. Offers to run `save_cookies.py` right away
7. Installs and starts the launchd worker (auto-starts on login, runs in background)

After setup, fill in `.env`:

```env
GOOGLE_API_KEY=...       # from aistudio.google.com/apikey
WORKER_NAME=your-name    # e.g. arjun-mbp — must be unique across team
```

Then authenticate with GCP (one-time):
```bash
gcloud auth application-default login
```

---

## Common commands

```bash
make cookies        # refresh LinkedIn session (browser opens, log in, press Enter)
make worker-logs    # tail live worker output
make worker-stop    # stop the background worker
make worker-start   # start it again
make worker-restart # restart (e.g. after a code change)
make worker-status  # check if worker process is running
make worker         # run worker in foreground (useful for debugging)
```

---

## Refreshing LinkedIn session cookies

LinkedIn sessions last ~1 year. When they expire the worker will fail with auth errors.

```bash
make cookies
# Browser opens → log into LinkedIn → press Enter
# Then push the new session to Cloud Run:
curl -X POST https://linkedin-api-461238503904.us-central1.run.app/admin/session \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d @linkedin_storage.json
```

---

## API usage

All requests require `X-API-Key` header.

### Submit a job

**Person (mutual connections):**
```bash
curl -X POST https://linkedin-api-461238503904.us-central1.run.app/jobs \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.linkedin.com/in/someprofile"}'
```

**Company (employee connections):**
```bash
curl -X POST https://linkedin-api-461238503904.us-central1.run.app/jobs \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.linkedin.com/company/acme", "job_type": "company_people"}'
```

Returns immediately with `job_id` and `status: pending`.

### Poll for result

```bash
curl https://linkedin-api-461238503904.us-central1.run.app/jobs/JOB_ID \
  -H "X-API-Key: YOUR_KEY"
```

`status` will be `pending` → `running` → `completed` (or `failed` / `dead`).

### List all jobs

```bash
curl "https://linkedin-api-461238503904.us-central1.run.app/jobs?status=completed" \
  -H "X-API-Key: YOUR_KEY"
```

### Force re-scrape (bypass 90-day cache)

```bash
curl -X POST .../jobs \
  -H "X-API-Key: YOUR_KEY" \
  -d '{"url": "...", "force_refresh": true}'
```

---

## Output format

### `mutual_connections`
```json
{
  "target_profile": "https://www.linkedin.com/in/someprofile/",
  "mutual_count": 21,
  "extracted_at": "2026-02-26T11:35:56Z",
  "actual_extracted": 21,
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

### `company_people`
```json
{
  "meta": {
    "company_url": "https://www.linkedin.com/company/acme",
    "company_name": "Acme Corp",
    "extracted_at": "2026-02-27T10:00:00Z",
    "total_employees_visible": 45,
    "total_captured": 40,
    "second_degree_count": 12,
    "by_degree": { "1st": 2, "2nd": 12, "3rd+": 26 }
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

## Dead letter queue

After 5 failed delivery attempts, Pub/Sub moves the message to `linkedin-jobs-dead`. The job is marked `status: dead` in Firestore and a Slack alert is sent.

**Inspect dead messages:**
```bash
gcloud pubsub subscriptions pull linkedin-jobs-dead-sub \
  --limit=10 --auto-ack \
  --project=chromatic-being-375320
```

**Replay a dead job** (re-submit via API — don't move the DLQ message):
```bash
curl -X POST https://linkedin-api-461238503904.us-central1.run.app/jobs \
  -H "X-API-Key: YOUR_KEY" \
  -d '{"url": "https://www.linkedin.com/in/thatperson", "force_refresh": true}'
```

---

## Multi-machine setup

Multiple team Macs can all run the worker simultaneously. Pub/Sub delivers each job to exactly one machine — whoever polls first gets it. The Firestore job document records `worker_host` so you can see which machine processed each job.

Each machine needs its own:
- `linkedin_storage.json` (same LinkedIn account — copy from whoever ran `save_cookies.py`)
- `.env` with a unique `WORKER_NAME`
- gcloud ADC credentials (`gcloud auth application-default login`)

---

## File structure

```
linkedin_mutual/
├── api/                      ← Cloud Run API package
│   ├── main.py               ← FastAPI app + routes
│   ├── config.py             ← Settings (pydantic)
│   ├── store.py              ← Firestore helpers
│   ├── pubsub.py             ← Pub/Sub publish helper
│   ├── slack.py              ← Slack alert helper
│   └── models.py             ← Request/response models
├── mutual_connections.py     ← Person scraper
├── company_people.py         ← Company scraper
├── worker.py                 ← Local Pub/Sub worker (runs via launchd)
├── save_cookies.py           ← One-time LinkedIn session saver
├── setup.sh                  ← One-command new contributor setup
├── Makefile                  ← Common dev commands
├── Dockerfile                ← Cloud Run image (API only, no browser)
├── pyproject.toml            ← Dependencies
├── .env.example              ← Template — copy to .env and fill in
├── airtable_sync_spec.md     ← Spec for the separate Airtable sync service
└── com.frontier.linkedin-worker.plist  ← launchd template (generated by setup.sh)
```

---

## Notes

- `linkedin_storage.json` and `.env` are git-ignored — never commit them.
- If LinkedIn redirects to login, re-run `make cookies` and push the new session.
- To extract more connections on large lists, increase `--max-steps` (default: 60 for mutual connections, 80 for company people).
- The worker runs at background priority (`Nice=10`) so it won't compete with foreground apps or spin up fans.

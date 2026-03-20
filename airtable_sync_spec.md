# Airtable Sync — Cloud Function Spec

## Purpose

A standalone GCP Cloud Function that listens for completed LinkedIn scrape jobs
in Firestore and writes the results to Airtable. Lives in its own repository,
completely separate from the LinkedIn scraper.

---

## System Context

### Upstream: LinkedIn Scraper (separate repo)

The scraper runs as two components:
1. **Cloud Run API** (`linkedin-api-461238503904.us-central1.run.app`) — accepts
   job requests, publishes to Pub/Sub
2. **Local worker** (runs on a Mac via launchd) — pulls jobs from Pub/Sub, runs
   a Playwright/Gemini browser agent, writes results to Firestore

When a job finishes, the worker writes a Firestore document to the `jobs`
collection in database `linkedin-api` (GCP project `chromatic-being-375320`).

### Two job types

**`mutual_connections`** — scrapes mutual connections between the logged-in user
and a target LinkedIn profile.

**`company_people`** — scrapes all visible employees on a LinkedIn company's
`/people/` tab (captures 1st, 2nd, 3rd+ degree connections).

---

## Trigger

**Firestore `onDocumentUpdated`** on:
```
projects/chromatic-being-375320/databases/linkedin-api/documents/jobs/{job_id}
```

Fire only when `status` transitions **to** `"completed"`. Ignore all other
updates (pending → running, failures, etc.).

```python
# Pseudo-condition inside the function
before = event.data.before.to_dict()
after  = event.data.after.to_dict()

if before.get("status") == "completed":
    return  # already processed, idempotency guard
if after.get("status") != "completed":
    return  # not done yet
```

---

## Firestore Job Document Schema

```json
{
  "job_id":     "uuid-string",
  "job_type":   "mutual_connections" | "company_people",
  "url":        "https://www.linkedin.com/in/username",
  "status":     "pending" | "running" | "completed" | "failed",
  "created_at": "<Firestore Timestamp>",
  "started_at": "<Firestore Timestamp>",
  "finished_at":"<Firestore Timestamp>",
  "result":     { ... },
  "error":      null,
  "cache_key":  "in__username"
}
```

---

## Result Payloads

### mutual_connections

```json
{
  "target_profile": "https://www.linkedin.com/in/someprofile",
  "mutual_count": 15,
  "extracted_at": "2026-03-19T10:00:00Z",
  "actual_extracted": 15,
  "mutual_connections": [
    {
      "name": "Full Name",
      "linkedin_url": "https://www.linkedin.com/in/username",
      "linkedin_id": "username",
      "title": "Partner @ Acme | Investor",
      "company": "Acme",
      "location": "New York, NY"
    }
  ]
}
```

### company_people

```json
{
  "meta": {
    "company_url": "https://www.linkedin.com/company/acme",
    "company_name": "Acme Corp",
    "people_tab_url": "https://www.linkedin.com/company/acme/people/",
    "extracted_at": "2026-03-19T10:00:00Z",
    "total_employees_visible": 50,
    "total_captured": 45,
    "second_degree_count": 12,
    "by_degree": { "1st": 2, "2nd": 12, "3rd+": 31 }
  },
  "people": [
    {
      "name": "Full Name",
      "linkedin_url": "https://www.linkedin.com/in/username",
      "linkedin_id": "username",
      "title": "VP of Engineering",
      "location": "San Francisco, CA",
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

## Airtable Schema (recommended)

Design around three tables. Adapt field names to match your existing base if one
already exists.

### Table: `People`
| Field            | Type            | Notes                                     |
|------------------|-----------------|-------------------------------------------|
| `linkedin_id`    | Single line     | Primary key for upsert — use this to deduplicate |
| `Name`           | Single line     |                                           |
| `LinkedIn URL`   | URL             |                                           |
| `Title`          | Single line     | Most recent headline from scrape          |
| `Company`        | Single line     | For mutual_connections results            |
| `Location`       | Single line     |                                           |
| `Connection Degree` | Single select | `1st`, `2nd`, `3rd+`, `unknown`          |
| `Tags`           | Multiple select |                                           |
| `Notes`          | Long text       |                                           |
| `Contacted`      | Checkbox        |                                           |
| `Contact Date`   | Date            |                                           |
| `Scrape Jobs`    | Link to `Scrape Jobs` | All jobs this person appeared in    |
| `Last Seen At`   | Date/time       | Updated on every scrape                   |

### Table: `Scrape Jobs`
| Field          | Type                  | Notes                                       |
|----------------|-----------------------|---------------------------------------------|
| `job_id`       | Single line           | Primary key for upsert                      |
| `Job Type`     | Single select         | `mutual_connections`, `company_people`      |
| `Target URL`   | URL                   | The URL that was scraped                    |
| `Status`       | Single select         | Always `completed` when synced              |
| `Scraped At`   | Date/time             | `finished_at` from Firestore                |
| `People Count` | Number                | How many people extracted                   |
| `People`       | Link to `People`      | All people found in this job                |

### Table: `Companies` *(optional, useful for company_people jobs)*
| Field          | Type        | Notes                          |
|----------------|-------------|--------------------------------|
| `linkedin_id`  | Single line | slug from URL, e.g. `acme`     |
| `Name`         | Single line |                                |
| `LinkedIn URL` | URL         |                                |
| `Scrape Jobs`  | Link to `Scrape Jobs` |                      |

---

## Upsert Strategy (critical for idempotency)

The function will be retried by GCP if it throws. All Airtable writes must be
safe to run twice.

1. **People** — upsert on `linkedin_id`. Check if a record with that `linkedin_id`
   exists via Airtable `filterByFormula`. If yes, PATCH; if no, POST.
2. **Scrape Jobs** — upsert on `job_id`. Same pattern.
3. **Link records** — collect Airtable record IDs after upserting People, then
   PATCH the Scrape Jobs record with those IDs.

Airtable's native upsert endpoint (`PATCH /records?performUpsert`) is the
cleanest approach — use it if available on your plan. Otherwise implement
check-then-write manually.

---

## Tech Stack

| Component      | Choice           | Reason                                    |
|----------------|------------------|-------------------------------------------|
| Runtime        | Python 3.12      | Matches scraper stack                     |
| Trigger        | Cloud Functions v2 | Native Firestore trigger, Gen 2 = better cold starts |
| Firestore SDK  | `google-cloud-firestore` | Read job doc if needed          |
| Airtable SDK   | `pyairtable`     | Best-maintained Python Airtable client    |
| Secrets        | Secret Manager   | Airtable API key stored there             |
| Auth           | Service account  | Same GCP project, ADC locally             |

---

## Environment Variables / Secrets

| Variable            | Where        | Value                                     |
|---------------------|--------------|-------------------------------------------|
| `AIRTABLE_API_KEY`  | Secret Manager | Personal Access Token from airtable.com/create/tokens |
| `AIRTABLE_BASE_ID`  | Env var      | `appXXXXXXXXXXXXXX` from your base URL   |
| `AIRTABLE_PEOPLE_TABLE` | Env var  | Table name, e.g. `People`                |
| `AIRTABLE_JOBS_TABLE`   | Env var  | Table name, e.g. `Scrape Jobs`            |
| `GCP_PROJECT_ID`    | Env var      | `chromatic-being-375320`                  |

---

## File Structure

```
linkedin-airtable-sync/
├── main.py              ← Cloud Function entry point
├── airtable_client.py   ← Upsert helpers (People, Scrape Jobs, Companies)
├── mappers.py           ← Transform Firestore result → Airtable field dicts
├── requirements.txt
├── .env.example
└── README.md
```

---

## Function Entry Point

```python
# main.py
import functions_framework
from google.events.cloud.firestore import DocumentEventData

@functions_framework.cloud_event
def on_job_completed(cloud_event):
    data = DocumentEventData()
    data._pb.MergeFromString(cloud_event.data)

    before = firestore_dict(data.old_value)
    after  = firestore_dict(data.value)

    if before.get("status") == "completed":
        return  # idempotency: already synced
    if after.get("status") != "completed":
        return  # not done yet

    job_type = after.get("job_type", "mutual_connections")
    result   = after.get("result", {})

    if job_type == "mutual_connections":
        sync_mutual_connections(after, result)
    elif job_type == "company_people":
        sync_company_people(after, result)
```

---

## GCP Setup (one-time)

```bash
# Enable required APIs
gcloud services enable cloudfunctions.googleapis.com \
    cloudbuild.googleapis.com \
    eventarc.googleapis.com \
    --project=chromatic-being-375320

# Create a service account for the function
gcloud iam service-accounts create airtable-sync-sa \
    --display-name="Airtable Sync Function" \
    --project=chromatic-being-375320

# Grant it Firestore read access
gcloud projects add-iam-policy-binding chromatic-being-375320 \
    --member="serviceAccount:airtable-sync-sa@chromatic-being-375320.iam.gserviceaccount.com" \
    --role="roles/datastore.viewer"

# Store Airtable key in Secret Manager
gcloud secrets create airtable-api-key \
    --data-file=- \
    --project=chromatic-being-375320 <<< "YOUR_AIRTABLE_TOKEN"

# Grant function SA access to the secret
gcloud secrets add-iam-policy-binding airtable-api-key \
    --member="serviceAccount:airtable-sync-sa@chromatic-being-375320.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor" \
    --project=chromatic-being-375320
```

---

## Deploy Command

```bash
gcloud functions deploy linkedin-airtable-sync \
    --gen2 \
    --runtime=python312 \
    --region=us-central1 \
    --source=. \
    --entry-point=on_job_completed \
    --trigger-event-filters="type=google.cloud.firestore.document.v1.updated" \
    --trigger-event-filters="database=linkedin-api" \
    --trigger-event-filters-path-pattern="document=jobs/{job_id}" \
    --service-account=airtable-sync-sa@chromatic-being-375320.iam.gserviceaccount.com \
    --set-env-vars="GCP_PROJECT_ID=chromatic-being-375320,AIRTABLE_BASE_ID=appXXX,AIRTABLE_PEOPLE_TABLE=People,AIRTABLE_JOBS_TABLE=Scrape Jobs" \
    --set-secrets="AIRTABLE_API_KEY=airtable-api-key:latest" \
    --memory=256Mi \
    --timeout=120s \
    --project=chromatic-being-375320
```

---

## Key Implementation Notes for the Developer

1. **Parse Firestore Timestamps** — `created_at`, `finished_at` etc. come back as
   `google.protobuf.Timestamp` objects when decoded from the event payload. Convert
   with `.ToDatetime()` before formatting for Airtable.

2. **Firestore event payload decoding** — Use the
   `functions-framework` + `google-events` libraries. The raw protobuf needs to be
   decoded via `DocumentEventData`. See the entry point above.

3. **Rate limits** — Airtable allows 5 requests/second per base. If a company
   scrape returns 200+ people, batch writes into groups of 10 (Airtable's max per
   request) and add a small `time.sleep(0.25)` between batches.

4. **Linked records** — when linking People → Scrape Jobs, you need the Airtable
   record ID (e.g. `recXXXXXXXXXXXXXX`), not the `linkedin_id`. Collect record IDs
   returned from the People upsert calls, then include them in the Scrape Jobs write.

5. **Local testing** — Use the Functions Framework to test locally:
   ```bash
   pip install functions-framework
   functions-framework --target=on_job_completed --dry-run
   ```
   For integration tests, fire a real Firestore update on a test document and watch
   the function trigger.

6. **Retry behaviour** — Cloud Functions v2 retries on unhandled exceptions. The
   idempotency guard at the top (`before.status == completed → return`) prevents
   duplicate Airtable records on retry.

---

## Dependencies (`requirements.txt`)

```
functions-framework==3.*
google-events==0.8.*
google-cloud-firestore==2.*
google-cloud-secret-manager==2.*
pyairtable==2.*
```

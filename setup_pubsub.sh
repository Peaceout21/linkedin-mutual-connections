#!/bin/bash
# One-time GCP setup: creates Pub/Sub topic + subscription
# Run once: bash setup_pubsub.sh

set -e

PROJECT_ID="chromatic-being-375320"
TOPIC="linkedin-jobs"
SUBSCRIPTION="linkedin-jobs-local"
CLOUD_RUN_SA="linkedin-api-sa@${PROJECT_ID}.iam.gserviceaccount.com"

echo "Setting up Pub/Sub for project: $PROJECT_ID"

# Create topic
echo "Creating topic: $TOPIC"
gcloud pubsub topics create $TOPIC \
  --project=$PROJECT_ID 2>/dev/null || echo "  (already exists)"

# Create pull subscription (local worker pulls from this)
# Message retention: 7 days (so jobs aren't lost over a long weekend)
# Ack deadline: 300s (5 min) — worker extends this during long scrapes
echo "Creating subscription: $SUBSCRIPTION"
gcloud pubsub subscriptions create $SUBSCRIPTION \
  --topic=$TOPIC \
  --ack-deadline=300 \
  --message-retention-duration=7d \
  --expiration-period=never \
  --project=$PROJECT_ID 2>/dev/null || echo "  (already exists)"

# Grant Cloud Run service account permission to publish to the topic
echo "Granting Cloud Run SA publish rights on topic"
gcloud pubsub topics add-iam-policy-binding $TOPIC \
  --member="serviceAccount:${CLOUD_RUN_SA}" \
  --role="roles/pubsub.publisher" \
  --project=$PROJECT_ID

# Grant your local ADC (gcloud account) permission to pull + ack
ACCOUNT=$(gcloud config get-value account)
echo "Granting $ACCOUNT subscriber rights on subscription"
gcloud pubsub subscriptions add-iam-policy-binding $SUBSCRIPTION \
  --member="user:${ACCOUNT}" \
  --role="roles/pubsub.subscriber" \
  --project=$PROJECT_ID

echo ""
echo "Done! Pub/Sub setup complete."
echo ""
echo "Next steps:"
echo "  1. Deploy Cloud Run:  gcloud builds submit ..."
echo "  2. Start worker:      python worker.py"
echo "  3. Install launchd:   cp com.frontier.linkedin-worker.plist ~/Library/LaunchAgents/"
echo "                        launchctl load ~/Library/LaunchAgents/com.frontier.linkedin-worker.plist"

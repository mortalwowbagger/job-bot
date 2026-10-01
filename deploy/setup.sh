#!/usr/bin/env bash
# One-time Google Cloud setup for the hosted job-bot. Safe to re-run (skips what exists).
#   bash deploy/setup.sh
# Needs: gcloud logged in (gcloud auth login), billing on the project, ANTHROPIC_API_KEY in .env
set -euo pipefail
PROJECT=${PROJECT:-job-bot-app}
REGION=${REGION:-us-central1}
BUCKET=${BUCKET:-$PROJECT-packets}
SA=jobbot-runner@$PROJECT.iam.gserviceaccount.com
gc() { gcloud --project "$PROJECT" --quiet "$@"; }

echo "== APIs"
gc services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com firestore.googleapis.com cloudscheduler.googleapis.com \
  storage.googleapis.com iam.googleapis.com identitytoolkit.googleapis.com

echo "== Firestore (native mode, $REGION)"
gc firestore databases describe --database='(default)' >/dev/null 2>&1 || \
  gc firestore databases create --location="$REGION"

echo "== Private bucket for packet PDFs: gs://$BUCKET"
gc storage buckets describe "gs://$BUCKET" >/dev/null 2>&1 || \
  gc storage buckets create "gs://$BUCKET" --location="$REGION" \
    --uniform-bucket-level-access --public-access-prevention

echo "== Docker image repository"
gc artifacts repositories describe jobbot --location="$REGION" >/dev/null 2>&1 || \
  gc artifacts repositories create jobbot --repository-format=docker --location="$REGION"

echo "== Anthropic API key -> Secret Manager (value never printed)"
if ! gc secrets describe anthropic-api-key >/dev/null 2>&1; then
  KEY=$(grep -E '^ANTHROPIC_API_KEY=' .env | head -1 | cut -d= -f2- | tr -d '"'"'"' \r\n')
  [ -n "$KEY" ] || { echo "ANTHROPIC_API_KEY missing from .env"; exit 1; }
  printf '%s' "$KEY" | gc secrets create anthropic-api-key --replication-policy=automatic --data-file=-
fi

echo "== Optional job-source keys (.env -> Secret Manager, values never printed)"
for pair in MUSE_API_KEY:muse-api-key ADZUNA_APP_ID:adzuna-app-id ADZUNA_APP_KEY:adzuna-app-key; do
  VAR=${pair%%:*}; NAME=${pair##*:}
  VAL=$(grep -E "^$VAR=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"' \r\n' || true)
  [ -n "$VAL" ] || { echo "  $VAR not in .env (skipped)"; continue; }
  if gc secrets describe "$NAME" >/dev/null 2>&1; then
    printf '%s' "$VAL" | gc secrets versions add "$NAME" --data-file=- >/dev/null && echo "  $NAME updated"
  else
    printf '%s' "$VAL" | gc secrets create "$NAME" --replication-policy=automatic --data-file=- >/dev/null && echo "  $NAME created"
  fi
done

echo "== Service account the app and daily run use: $SA"
gc iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  gc iam service-accounts create jobbot-runner --display-name="job-bot web + daily run"
for role in roles/datastore.user roles/run.developer roles/logging.logWriter; do
  gc projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" --role="$role" \
    --condition=None >/dev/null
done
gc storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$SA" \
  --role=roles/storage.objectAdmin >/dev/null
for NAME in anthropic-api-key muse-api-key adzuna-app-id adzuna-app-key; do
  gc secrets describe "$NAME" >/dev/null 2>&1 && gc secrets add-iam-policy-binding "$NAME" \
    --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor >/dev/null
done
# lets the web app start the run job, which runs as this same account
gc iam service-accounts add-iam-policy-binding "$SA" --member="serviceAccount:$SA" \
  --role=roles/iam.serviceAccountUser >/dev/null

echo "== Cloud Build may push images and write logs"
PN=$(gc projects describe "$PROJECT" --format='value(projectNumber)')
for m in "serviceAccount:$PN-compute@developer.gserviceaccount.com" "serviceAccount:$PN@cloudbuild.gserviceaccount.com"; do
  for role in roles/artifactregistry.writer roles/logging.logWriter roles/storage.objectViewer; do
    gc projects add-iam-policy-binding "$PROJECT" --member="$m" --role="$role" --condition=None >/dev/null 2>&1 || true
  done
done

echo "Setup done."

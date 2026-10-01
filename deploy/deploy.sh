#!/usr/bin/env bash
# Build the image and release the hosted job-bot. Re-run after any code change.
#   bash deploy/deploy.sh
# First time: bash deploy/setup.sh.
# JOBBOT_ADMIN_EMAILS: owner(s), default = your gcloud account. Sign-up mode and limits: config.yaml (cloud:).
set -euo pipefail
PROJECT=${PROJECT:-job-bot-app}
REGION=${REGION:-us-central1}
BUCKET=${BUCKET:-$PROJECT-packets}
SA=jobbot-runner@$PROJECT.iam.gserviceaccount.com
ADMINS=${JOBBOT_ADMIN_EMAILS:-$(gcloud config get-value account 2>/dev/null)}
gc() { gcloud --project "$PROJECT" --quiet "$@"; }

if [ -z "${IMAGE:-}" ]; then  # IMAGE=... reuses an already-built image
  IMAGE=$REGION-docker.pkg.dev/$PROJECT/jobbot/app:$(date +%Y%m%d-%H%M%S)
  echo "== Build $IMAGE (in Cloud Build, no local Docker needed)"
  gc builds submit --region="$REGION" --tag="$IMAGE" .
fi

ENVFILE=$(mktemp)
trap 'rm -f "$ENVFILE"' EXIT
python3 - "$ENVFILE" "$PROJECT" "$REGION" "$BUCKET" "$ADMINS" <<'PY'
import json, sys
out, project, region, bucket, admins = sys.argv[1:]
cfg = json.load(open("deploy/firebase-web-config.json"))
env = {"GOOGLE_CLOUD_PROJECT": project, "JOBBOT_REGION": region, "JOBBOT_BUCKET": bucket,
       "JOBBOT_RUN_JOB": "jobbot-run", "JOBBOT_ADMIN_EMAILS": admins,
       "JOBBOT_FIREBASE_CONFIG": json.dumps(cfg)}
with open(out, "w") as f:
    for k, v in env.items():
        f.write(f"{k}: {json.dumps(v)}\n")
PY

echo "== Run job (daily search + Run button)"
SECRETS=ANTHROPIC_API_KEY=anthropic-api-key:latest
for pair in MUSE_API_KEY:muse-api-key ADZUNA_APP_ID:adzuna-app-id ADZUNA_APP_KEY:adzuna-app-key; do
  gc secrets describe "${pair##*:}" >/dev/null 2>&1 && SECRETS="$SECRETS,${pair%%:*}=${pair##*:}:latest"
done
gc run jobs deploy jobbot-run --image="$IMAGE" --region="$REGION" --service-account="$SA" \
  --command=python,-m,jobbot.cloud.pipeline --env-vars-file="$ENVFILE" \
  --set-secrets="$SECRETS" \
  --memory=2Gi --cpu=1 --task-timeout=60m --max-retries=0

echo "== Web service"
gc run deploy jobbot-web --image="$IMAGE" --region="$REGION" --service-account="$SA" \
  --env-vars-file="$ENVFILE" --set-secrets=ANTHROPIC_API_KEY=anthropic-api-key:latest \
  --allow-unauthenticated --memory=512Mi --cpu=1 --timeout=120 \
  --min-instances=0 --max-instances=2 --concurrency=20

echo "== Daily schedule: 7:00 America/Chicago"
URI="https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/jobbot-run:run"
if gc scheduler jobs describe jobbot-daily --location="$REGION" >/dev/null 2>&1; then
  gc scheduler jobs update http jobbot-daily --location="$REGION" --schedule="0 7 * * *" \
    --time-zone="America/Chicago" --uri="$URI" --http-method=POST --oauth-service-account-email="$SA"
else
  gc scheduler jobs create http jobbot-daily --location="$REGION" --schedule="0 7 * * *" \
    --time-zone="America/Chicago" --uri="$URI" --http-method=POST --oauth-service-account-email="$SA"
fi

echo "== Firebase Hosting + Firestore rules"
firebase deploy --only hosting,firestore:rules --project "$PROJECT"
echo "Live: https://$PROJECT.web.app"

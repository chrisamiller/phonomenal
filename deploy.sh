#!/usr/bin/env bash
# Build, push and roll out a new version of the app to Cloud Run.
#
#   ./deploy.sh              # test, back up Firestore, build with Docker on this Mac, push, deploy
#   ./deploy.sh --no-backup  # skip the Firestore backup
#   ./deploy.sh --no-tests   # skip the test suite
#
# Only the image changes. Env vars, secrets, the media bucket mount and scaling settings carry over
# from the existing service, and Firestore isn't touched (the backup only reads it). Setup and the
# first deploy are in docs/deploy-gcp.md.
#
# The project ID comes from deploy.env (not in git; copy deploy.env.example) or the environment.
set -euo pipefail
cd "$(dirname "$0")"

[[ -f deploy.env ]] && source deploy.env
: "${PROJECT_ID:?set PROJECT_ID in deploy.env (cp deploy.env.example deploy.env) or the environment}"
REGION=${REGION:-us-central1}
SERVICE=${SERVICE:-spelling}
IMAGE=${IMAGE:-$REGION-docker.pkg.dev/$PROJECT_ID/spelling/app}

backup=true tests=true
for arg in "$@"; do
  case $arg in
    --no-backup) backup=false ;;
    --no-tests) tests=false ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 1 ;;
  esac
done

# Tag: date + commit, marked -dirty when there are uncommitted changes, so you can tell what's live.
sha=$(git rev-parse --short HEAD 2>/dev/null || echo nogit)
[[ -n $(git status --porcelain --untracked-files=no 2>/dev/null) ]] && sha+="-dirty"
TAG=$(date +%Y%m%d-%H%M)-$sha

docker info >/dev/null 2>&1 || { echo "Docker isn't running: start Docker Desktop and try again." >&2; exit 1; }

echo "==> Deploying $SERVICE ($PROJECT_ID, $REGION) as $IMAGE:$TAG"
current=$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" \
          --format='value(spec.template.spec.containers[0].image)')
echo "    currently live: $current"

if $tests; then
  echo "==> Running tests"
  .venv/bin/python -m pytest -q
fi

if $backup; then
  mkdir -p backups
  out=backups/spelling-backup-$(date +%Y-%m-%d-%H%M)-predeploy.json
  echo "==> Backing up Firestore to $out"
  SPELLING_STORE=firestore SPELLING_FIRESTORE_PROJECT=$PROJECT_ID .venv/bin/python -m app.cli export-backup "$out"
fi

echo "==> Building and pushing"
docker buildx build --platform linux/amd64 -t "$IMAGE:$TAG" --push .   # Cloud Run needs amd64

echo "==> Rolling out"
gcloud run deploy "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE:$TAG"

echo
echo "Done: $IMAGE:$TAG is live."
echo "To roll back: gcloud run deploy $SERVICE --project $PROJECT_ID --region $REGION --image $current"

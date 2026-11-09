# Deploying to Google Cloud

How to run the app on **Cloud Run**, with data in **Firestore**, audio in **Cloud Storage**, and the
password in **Secret Manager**. Every step is a command you run yourself. Nothing here has been run
for you.

| Piece | Where it lives |
|---|---|
| The web app | A Cloud Run service built from the `Dockerfile` in the project root. It scales to zero when nobody is practising. |
| Words, progress, credits, aquarium… | Firestore, through `FirestoreStore` in `app/store.py` (selected with `SPELLING_STORE=firestore`). |
| Word and sentence audio (about 70 MB) | A Cloud Storage bucket, mounted read-only into the container at `/data/media`. |
| Sound-match clips (about 7 MB) | The same bucket, under `phonics_sounds/`. Upload with `gcloud storage rsync --recursive phonics_sounds gs://$BUCKET/phonics_sounds`. |
| Settings, shop, list of sounds, pronouncing dictionary | Baked into the container image. |
| Password and cookie-signing key | Secret Manager. |
| Backups | Firestore's daily scheduled backups (kept 14 weeks), plus **Export backup** on the grown-ups' page for copies on your Mac. |

## Before you start

You need `gcloud` installed and logged in, with a project that has billing linked. The TTS setup in
`docs/google-tts.md` already did this. Set these once per terminal; every command below uses them:

```bash
export PROJECT_ID=your-project-id          # gcloud config get-value project
export REGION=us-central1                  # Cloud Run, Artifact Registry and the bucket
export FS_LOCATION=us-central1                    # Firestore multi-region (US); or a single region like us-central1
export BUCKET=$PROJECT_ID-spelling-media   # bucket names are global; change it if it's taken
export SA=spelling-app@$PROJECT_ID.iam.gserviceaccount.com
export IMAGE=$REGION-docker.pkg.dev/$PROJECT_ID/spelling/app

gcloud config set project $PROJECT_ID
gcloud config set run/region $REGION
```

Also install the Firestore client locally. The command-line tools need it to talk to Firestore:

```bash
.venv/bin/pip install -r requirements-cloud.txt
```

## 1. Turn on the services

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
    firestore.googleapis.com secretmanager.googleapis.com storage.googleapis.com
```

This takes a minute or two. Set a budget alert now (for example $5) under **Billing → Budgets &
alerts** in the Cloud console.

## 2. Create the Firestore database, with daily backups

```bash
gcloud firestore databases create --database='(default)' --location=$FS_LOCATION \
    --type=firestore-native --delete-protection
gcloud firestore backups schedules create --database='(default)' --recurrence=daily --retention=14w
gcloud firestore backups schedules list --database='(default)'      # check it's there
```

- **Delete protection** stops the database being deleted by accident. It doesn't stop the app or
  `restore-backup` from changing data.
- **Backups:** one runs each day at a time Firestore picks, and each is kept 14 weeks (the longest
  allowed).
- **Point-in-time recovery is off,** as you chose.

## 3. Copy your data into Firestore

Use a fresh backup of your local data:

```bash
.venv/bin/python -m app.cli export-backup migrate.json            # from data/db.json
```

Let the local tools reach Firestore with your own Google login. TTS already set this up, but the
quota project must match:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project $PROJECT_ID
```

Then load the backup into Firestore. It shows the counts and asks you to type `restore`:

```bash
SPELLING_STORE=firestore SPELLING_FIRESTORE_PROJECT=$PROJECT_ID \
    .venv/bin/python -m app.cli restore-backup migrate.json
```

That writes about 3,000 documents, which takes under a minute. Check it worked:

```bash
SPELLING_STORE=firestore SPELLING_FIRESTORE_PROJECT=$PROJECT_ID .venv/bin/python -m app.cli stats
```

### Optional: try the app locally against Firestore first

This runs your Mac's copy of the app on the cloud database, so you can practise a few words before
deploying. Anything you do here changes the real Firestore data.

```bash
SPELLING_STORE=firestore SPELLING_FIRESTORE_PROJECT=$PROJECT_ID \
    .venv/bin/uvicorn app.main:app --port 8811
```

## 4. Upload the audio

```bash
gcloud storage buckets create gs://$BUCKET --location=$REGION --uniform-bucket-level-access
gcloud storage buckets update gs://$BUCKET --versioning        # overwritten or deleted clips can be recovered
.venv/bin/python -m app.cli prune-media                        # lists clips no word uses; add --delete to skip them
gcloud storage rsync --recursive data/media gs://$BUCKET
```

## 5. Secrets and the app's service account

The password, and a random key that signs the sign-in cookie. `read -s` asks for the password
without showing it or saving it in your shell history:

```bash
read -s -p "Password: " PW; echo
printf '%s' "$PW" | gcloud secrets create spelling-password --data-file=-
unset PW
openssl rand -hex 32 | gcloud secrets create spelling-secret-key --data-file=-
```

Keep the secret key the same across deploys: changing it signs her out. To change the password
later, add a new version the same way (`gcloud secrets versions add spelling-password --data-file=-`)
and redeploy (step 7), then disable the old version with `gcloud secrets versions disable`.

A service account for the app, allowed exactly what it needs:

```bash
gcloud iam service-accounts create spelling-app --display-name="Spelling app"

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SA" --role=roles/datastore.user            # read and write Firestore
gcloud storage buckets add-iam-policy-binding gs://$BUCKET \
    --member="serviceAccount:$SA" --role=roles/storage.objectViewer      # read the audio
for s in spelling-password spelling-secret-key; do
  gcloud secrets add-iam-policy-binding $s \
      --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor
done
```

## 6. Build the container image

There are two ways to build the image. Use either one.

### Option A: build on your Mac and push (no Cloud Build)

Your Mac has an Apple chip (arm64), and Cloud Run needs an `amd64` image, so always pass
`--platform linux/amd64`. An ARM image would deploy but then fail to start, with
`exec format error` in the logs.

```bash
gcloud artifacts repositories create spelling --repository-format=docker --location=$REGION
gcloud auth configure-docker $REGION-docker.pkg.dev        # once: lets docker push to Artifact Registry
docker buildx build --platform linux/amd64 -t $IMAGE:v1 --push .
```

This uses `.dockerignore` to decide what goes into the image. It takes about a minute, and the
first push uploads about 90 MB. Your own account pushes the image, so the Cloud Build permission in
Option B isn't needed. For later deploys, build with a new tag (`:v2`) the same way.

### Option B: build in Cloud Build

Newer projects run Cloud Build as the Compute Engine default service account, which can't read
the uploaded source until it has the Cloud Build role. Grant it once:

```bash
export PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
    --role=roles/cloudbuild.builds.builder
```

Then create the image repository and build:

```bash
gcloud artifacts repositories create spelling --repository-format=docker --location=$REGION
gcloud meta list-files-for-upload | wc -l     # optional check: about 300 files
gcloud builds submit --tag $IMAGE:v1
```

Cloud Build uploads the project and builds the `Dockerfile`, which takes 2–4 minutes. The upload
leaves out everything in `.gcloudignore` (your data, backups, audio, the venv and tests): `gcloud`
uses that file, not `.dockerignore`. It should be about 11 MB. If it says 100 MB or more,
`.gcloudignore` is missing.

## 7. Deploy

```bash
gcloud run deploy spelling \
  --image $IMAGE:v1 \
  --service-account $SA \
  --allow-unauthenticated \
  --execution-environment gen2 \
  --cpu 1 --memory 512Mi \
  --min-instances 0 --max-instances 1 \
  --set-env-vars SPELLING_STORE=firestore,SPELLING_FIRESTORE_PROJECT=$PROJECT_ID,SPELLING_USERNAME=Lexi \
  --set-secrets SPELLING_PASSWORD=spelling-password:latest,SPELLING_SECRET_KEY=spelling-secret-key:latest \
  --add-volume name=media,type=cloud-storage,bucket=$BUCKET,readonly=true \
  --add-volume-mount volume=media,mount-path=/data/media
```

What the options mean:
- `--allow-unauthenticated` lets the browser reach the URL. The app's own sign-in page protects
  everything except itself and the app's code files.
- `--execution-environment gen2` is needed for the bucket mount.
- `--max-instances 1`: one child doesn't need more, and a single instance keeps the in-memory cache
  simple.
- `--min-instances 0`: free when idle. The first visit after a quiet spell takes a few seconds while
  it starts. `--min-instances 1` removes that wait for roughly $10 a month.

The command prints the URL (`https://spelling-…-uc.a.run.app`). Then:
1. Open it on her device. You should get the sign-in page.
2. Sign in as Lexi and do a short spelling session.
3. Check the grown-ups' page at `<url>/progress`, and try **Export backup** there.
4. Check the logs for errors: `gcloud run services logs read spelling --limit 50`.

**Custom domain (optional):** run
`gcloud beta run domain-mappings create --service spelling --domain spelling.example.com` and add the
DNS records it prints. The certificate is issued automatically, within about 15 minutes to an hour.

## 8. Day-to-day

**Deploy a code change:** run `./deploy.sh`. It runs the tests, saves a Firestore backup to `backups/`,
builds a new image with Docker on your Mac (tagged with the date and commit), pushes it, and points the
service at it. It prints the
rollback command at the end. `./deploy.sh --help` lists the options. By hand, it's this: build with a
new tag, then point the service at it. Every other setting carries over:

```bash
docker buildx build --platform linux/amd64 -t $IMAGE:v2 --push .   # or: gcloud builds submit --tag $IMAGE:v2
gcloud run deploy spelling --image $IMAGE:v2
```

`settings.toml`, `shop.toml` and `achievements.toml` are inside the image, so editing them also
needs a new build and deploy.

**Add words:** run the usual tools against Firestore, then upload the new audio:

```bash
export SPELLING_STORE=firestore SPELLING_FIRESTORE_PROJECT=$PROJECT_ID
.venv/bin/python -m app.cli add new_words.csv            # also ranks them
.venv/bin/python -m app.cli build-phonics
.venv/bin/python -m app.cli generate-audio --engine google --voice en-US-Chirp3-HD-Leda --rate 0.85
gcloud storage rsync --recursive data/media gs://$BUCKET
```

The running app sees the new words on its next page load. No redeploy is needed.

**Roll back a bad deploy:**

```bash
gcloud run revisions list --service spelling
gcloud run services update-traffic spelling --to-revisions=REVISION_NAME=100
```

## 9. Backups and restoring

**Automatic:** Firestore makes a backup every day and keeps each one for 14 weeks. To list them:

```bash
gcloud firestore backups list --location=$FS_LOCATION
```

**Copies on your Mac:** the grown-ups' page has an **Export backup** link. It downloads everything
as one JSON file (`spelling-backup-YYYY-MM-DD.json`), in the same format as `data/db.json`. Grab one
every week or two and keep them somewhere safe. The same file works locally, too:
`.venv/bin/python -m app.cli export-backup`.

**Restore from a file on your Mac** (into Firestore, or into the local `data/db.json` if you leave
out the first line). It shows what's there now and what's in the file, asks you to type `restore`,
and saves the current data to `db.backup-before-restore-….json` in the local data folder first:

```bash
export SPELLING_STORE=firestore SPELLING_FIRESTORE_PROJECT=$PROJECT_ID
.venv/bin/python -m app.cli restore-backup spelling-backup-2026-11-14.json
```

Do this when she isn't practising. The running app picks up the restored data on its next page load.

**Restore from a Firestore daily backup:** Firestore restores a backup into a *new* database. Then
you copy it over the live one:

```bash
gcloud firestore backups list --location=$FS_LOCATION            # note the backup's ID and time
gcloud firestore databases restore \
    --source-backup=projects/$PROJECT_ID/locations/$FS_LOCATION/backups/BACKUP_ID \
    --destination-database=restored-20261114
# wait until it finishes:
gcloud firestore databases describe --database=restored-20261114

# Copy the restored data into the live database:
SPELLING_STORE=firestore SPELLING_FIRESTORE_PROJECT=$PROJECT_ID SPELLING_FIRESTORE_DATABASE=restored-20261114 \
    .venv/bin/python -m app.cli export-backup restored.json
SPELLING_STORE=firestore SPELLING_FIRESTORE_PROJECT=$PROJECT_ID \
    .venv/bin/python -m app.cli restore-backup restored.json

# Delete the temporary database when you're happy:
gcloud firestore databases delete --database=restored-20261114
```

Alternatively, point the app straight at the restored database:
`gcloud run services update spelling --update-env-vars SPELLING_FIRESTORE_DATABASE=restored-20261114`.
That's quicker, but then the daily backup schedule (which belongs to `(default)`) no longer covers
the data she's using.

It's worth doing a practice restore once, after the first few backups exist, with the file
method into your local copy.

## Costs

Everything here fits in the free tiers at this size:

| Service | Free tier | This app |
|---|---|---|
| Cloud Run | 2M requests and 180,000 vCPU-seconds a month | Well under |
| Firestore | 50k reads, 20k writes a day; 1 GiB stored | A few hundred writes a day; about 10 MB stored |
| Cloud Storage | 5 GB (in US regions) | About 70 MB |
| Artifact Registry | 0.5 GB | One image is about 400 MB, so delete old ones after each deploy (`gcloud artifacts docker images list $IMAGE`, then `… delete $IMAGE:v1`). |

The likely costs are cents a month: daily backup storage (billed per GiB, and the database is about
10 MB), plus about $10 a month if you choose `--min-instances 1`.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `gcloud builds submit`: `…-compute@developer.gserviceaccount.com does not have storage.objects.get access` | The build service account needs the Cloud Build role (step 6). Grant it, wait a minute, and retry. |
| `gcloud builds submit` uploads 100+ MB / thousands of files | `.gcloudignore` is missing from the project folder. |
| `403 … Cloud Firestore API has not been used` | Step 1 hasn't finished. Wait a minute and retry. |
| The local tools say `DefaultCredentialsError` | Run `gcloud auth application-default login`. |
| The local tools say `PERMISSION_DENIED` on Firestore | Your account needs access to the project (Owner or Editor), or set the quota project as in step 3. |
| The deploy fails on the volume | Check `--execution-environment gen2`, and that the bucket name is right. |
| The app loads but there's no audio | Check the bucket has the files (`gcloud storage ls gs://$BUCKET | head`), and that the service account has `storage.objectViewer` on it. |
| Every page sends you back to sign-in | The cookie key changed, or the browser blocks cookies. Check `SPELLING_SECRET_KEY` is set from the secret. |
| The first load is slow | That's the cold start with `--min-instances 0`, and it's normal. |
| `Please sign in` from the API after a redeploy | Expected if `spelling-secret-key` was recreated. Sign in again. |
	
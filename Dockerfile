# Container for Cloud Run. See docs/deploy-gcp.md. Audio is not baked in: word and sentence clips
# and the sound-match clips (phonics_sounds/) come from a Cloud Storage bucket mounted at /data/media.
FROM python:3.12-slim
WORKDIR /app
# The app uses the server's local time for "today", mission rollover and time-of-day achievements
# (Early Bird / Night Owl). Cloud Run defaults to UTC, so pin the family's time zone.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-cloud.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-cloud.txt
COPY app app
COPY static static
# Sound-match clips aren't copied: they come from the media bucket (mounted at /data/media/phonics_sounds).
COPY settings.toml shop.toml achievements.toml prompts.txt ./
COPY data/phonics /data/phonics
ENV SPELLING_DATA_DIR=/data PORT=8080 PYTHONUNBUFFERED=1 TZ=America/Chicago
# --proxy-headers: Cloud Run terminates HTTPS, so trust its X-Forwarded-Proto (for the secure cookie).
CMD exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"

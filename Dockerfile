# job-bot hosted image: used by both the web service and the daily run job.
# Playwright's image ships Chromium (for resume PDFs); keep its version in sync
# with playwright==... in requirements-cloud.txt.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt requirements-cloud.txt ./
RUN pip install -r requirements.txt -r requirements-cloud.txt
COPY jobbot jobbot
COPY config.yaml .
# web service (Cloud Run sets $PORT); the run job overrides this with `python -m jobbot.cloud.pipeline`
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 120 "jobbot.cloud.webapp:make_app()"

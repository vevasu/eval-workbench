# The story generator as a container, for Google Cloud Run. Build from this folder:
#   gcloud run deploy story-generator --source examples/story-generator ...   (see README.md)
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The Eval Workbench SDK, installed from the Workbench that will receive the traces (it hosts the wheel at /sdk/).
ARG WORKBENCH_URL=https://eval-workbench-5lofnwh6hq-uc.a.run.app
ARG SDK_VERSION=0.2.0
RUN pip install --no-cache-dir "${WORKBENCH_URL}/sdk/eval_workbench-${SDK_VERSION}-py3-none-any.whl"

COPY app.py story.py index.html ./
ENV PYTHONUNBUFFERED=1

# Visitors enter their own OpenAI key on the page. Set EVAL_WORKBENCH_URL, EVAL_WORKBENCH_API_KEY and APP_VERSION in
# Cloud Run to send each story to the Workbench. Leave OPENAI_API_KEY unset, or every visitor would use yours.
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]

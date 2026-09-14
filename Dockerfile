# the scoring service, and nothing else - the harness runs against the
# container from outside, the way it would in any environment.
FROM python:3.11-slim

WORKDIR /app

# layer order: requirements first so code edits reuse the dependency layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sut/ sut/

EXPOSE 8080

# the same probe k8s uses; a broken coefficients file fails the container
# at startup instead of at the first customer request
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz')"

CMD ["uvicorn", "sut.app:app", "--host", "0.0.0.0", "--port", "8080"]

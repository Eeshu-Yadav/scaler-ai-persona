# Build context must be the REPO ROOT (needs shared/ and data/):
#   docker build -f backend/Dockerfile -t persona-backend .
FROM python:3.12-slim

WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY shared /app/shared
COPY data /app/data
COPY backend /app/backend

ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
WORKDIR /app/backend

EXPOSE 8000
# gthread: SSE streams hold a worker thread each; 8 threads is plenty for eval traffic.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "2", "--threads", "8", "--timeout", "120"]

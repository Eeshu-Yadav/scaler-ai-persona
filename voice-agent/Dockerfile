# Build context must be the REPO ROOT (needs shared/ and data/):
#   docker build -f voice-agent/Dockerfile -t persona-voice .
FROM python:3.12-slim

WORKDIR /app
COPY voice-agent/requirements.txt /app/voice-agent/requirements.txt
RUN pip install --no-cache-dir -r voice-agent/requirements.txt

COPY shared /app/shared
COPY data /app/data
COPY voice-agent /app/voice-agent

ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
WORKDIR /app/voice-agent

# Pre-download VAD + end-of-utterance models so cold start is fast.
RUN python agent.py download-files

CMD ["python", "agent.py", "start"]

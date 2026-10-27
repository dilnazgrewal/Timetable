# TimeWeave public demo (Hugging Face Spaces, Docker SDK; any container host works the same way).
# The assistant (paid API) and optimiser re-runs (minutes of full CPU) are switched off: TIMEWEAVE_HOSTED=1.
FROM python:3.12-slim

# Spaces run the container as user 1000; the app writes data/state.json (demo changes, until a restart)
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .
USER user

ENV TIMEWEAVE_HOSTED=1 TIMEWEAVE_DEMO=1 PORT=7860 PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]

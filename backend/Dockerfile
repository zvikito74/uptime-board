FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Run as an unprivileged user; /data holds the SQLite file
RUN useradd --create-home appuser && mkdir /data && chown appuser /data
USER appuser

ENV DB_PATH=/data/uptime.db
EXPOSE 8000

# One worker, because the background checker runs inside the worker process
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:8000", "app:create_app()"]

# aioli: one image, and docker-entrypoint.sh picks the role - the board, the
# migrations, the clock. Nothing here runs as root.
FROM python:3.12-slim

RUN useradd --create-home --uid 1000 app
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chown -R app:app /app
USER app

ENV PYTHONUNBUFFERED=1
EXPOSE 8018

ENTRYPOINT ["./docker-entrypoint.sh"]

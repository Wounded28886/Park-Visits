# Park Visits, standalone — the same integration, without Home Assistant.
# Multi-arch (a Synology NAS may be x86_64 or ARM); no compiler needed, the
# dependencies ship wheels for both.
FROM python:3.12-slim

WORKDIR /app

RUN adduser --disabled-password --gecos "" --uid 1000 parks

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The integration source is copied in as-is: the container runs exactly the
# code the Home Assistant install runs.
COPY custom_components ./custom_components
COPY server ./server
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENV PORT=8098 \
    DATA_DIR=/data \
    TITLE="Park Visits" \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data && chown -R parks:parks /data /app
VOLUME ["/data"]
EXPOSE 8098

# Starts as root only to make the mounted data directory writable, then
# drops to the `parks` user (or PUID/PGID) for good. See the entrypoint.
ENTRYPOINT ["docker-entrypoint.sh"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8098')+'/healthz', timeout=4).status==200 else 1)"

CMD ["python", "server/app.py"]

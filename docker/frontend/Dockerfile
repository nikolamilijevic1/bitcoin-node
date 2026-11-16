FROM mempool/frontend:v3.2.1 AS upstream
FROM python:3.12.10-alpine AS patch
COPY --from=upstream /var/www/mempool/browser /original
COPY patch.py /patch.py
RUN python /patch.py /original /patched
FROM mempool/frontend:v3.2.1
COPY --from=patch --chown=1000:1000 /patched /var/www/mempool/browser

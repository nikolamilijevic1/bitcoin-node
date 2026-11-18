FROM mempool/backend:v3.2.1 AS upstream
FROM python:3.12.10-alpine AS patch
COPY --from=upstream /backend/package/api /original
COPY patch.py /patch.py
RUN python /patch.py /original /patched

FROM mempool/backend:v3.2.1
USER root
COPY --from=patch --chown=1000:1000 /patched /backend/package/api
RUN mkdir -p /backend/cache && chown 1000:1000 /backend/cache
USER 1000

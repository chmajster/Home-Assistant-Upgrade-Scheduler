ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.13-alpine3.22
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV HA_AUTOUPGRADE_DATA_DIR=/data

WORKDIR /app

COPY src /app/src
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]

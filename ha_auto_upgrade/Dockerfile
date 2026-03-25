ARG BUILD_FROM
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV HA_AUTOUPGRADE_DATA_DIR=/data

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src
COPY translations /app/translations
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]

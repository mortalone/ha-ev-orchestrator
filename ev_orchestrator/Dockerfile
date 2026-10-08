ARG BUILD_VERSION=0.3.0
ARG BUILD_ARCH=amd64
FROM ghcr.io/home-assistant/base-python:3.13-alpine3.24-2026.08.0

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
  io.hass.name="EV Orchestrator" \
  io.hass.description="Central EV monitor and legacy automation auditor" \
  io.hass.type="app" \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.arch="${BUILD_ARCH}"

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY app /app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]

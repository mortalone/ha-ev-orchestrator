ARG BUILD_VERSION=0.3.2
ARG BUILD_ARCH=amd64
FROM ghcr.io/home-assistant/base:latest

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
  io.hass.name="EV Orchestrator" \
  io.hass.description="Central EV monitor and legacy automation auditor" \
  io.hass.type="app" \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache \
    python3 \
    py3-aiohttp \
    py3-yaml

WORKDIR /app
COPY app /app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]

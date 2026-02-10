FROM debian:12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tinyproxy ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/tinyproxy /var/log/tinyproxy \
    && chown tinyproxy:tinyproxy /run/tinyproxy /var/log/tinyproxy

COPY --chmod=644 tinyproxy.conf /etc/tinyproxy/tinyproxy.conf

USER tinyproxy

EXPOSE 8888

CMD ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]

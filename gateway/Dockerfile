FROM debian:12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tinyproxy ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/tinyproxy \
    && chown nobody:nogroup /run/tinyproxy

COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf

USER tinyproxy

EXPOSE 8888

CMD ["tinyproxy", "-d"]

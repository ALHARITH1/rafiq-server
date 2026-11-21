FROM ghcr.io/alharith1/rafiq-server:base
USER root
COPY entrypoint.sh /usr/local/bin/rafiq-entrypoint.sh
COPY rafiq_backup.py /usr/local/bin/rafiq_backup.py
RUN chmod +x /usr/local/bin/rafiq-entrypoint.sh && mkdir -p /data && chown harith:harith /data
USER harith
ENTRYPOINT ["/usr/local/bin/rafiq-entrypoint.sh"]

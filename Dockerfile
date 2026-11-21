FROM ghcr.io/alharith1/rafiq-server:base
USER root
COPY entrypoint.sh /usr/local/bin/rafiq-entrypoint.sh
RUN chmod +x /usr/local/bin/rafiq-entrypoint.sh
USER harith
ENTRYPOINT ["/usr/local/bin/rafiq-entrypoint.sh"]

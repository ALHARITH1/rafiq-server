FROM ghcr.io/alharith1/rafiq-server:base
USER root
COPY entrypoint.sh /usr/local/bin/rafiq-entrypoint.sh
COPY rafiq_backup.py /usr/local/bin/rafiq_backup.py
COPY overlay/harith/customer_service.py /app/harith/customer_service.py
COPY overlay/harith/customer_connectors.py /app/harith/customer_connectors.py
COPY overlay/static/customer-service.js /app/harith/static/customer-service.js
COPY overlay/static/customer-chat.html /app/harith/static/customer-chat.html
COPY overlay/static/customer-chat.js /app/harith/static/customer-chat.js
COPY overlay/harith/temporary_password.py /app/harith/temporary_password.py
COPY overlay/static/change-password.html /app/harith/static/change-password.html
COPY overlay/static/change-password.js /app/harith/static/change-password.js
COPY overlay/apply_password_patch.py /tmp/apply_password_patch.py
COPY overlay/apply_cs_patch.py /tmp/apply_cs_patch.py
RUN chmod +x /usr/local/bin/rafiq-entrypoint.sh && mkdir -p /data && chown harith:harith /data \
 && python /tmp/apply_cs_patch.py \
 && python /tmp/apply_password_patch.py \
 && python -m py_compile /app/harith/customer_service.py /app/harith/core.py /app/harith/scheduler.py /app/harith/web.py \
 && rm /tmp/apply_cs_patch.py
USER harith
ENTRYPOINT ["/usr/local/bin/rafiq-entrypoint.sh"]

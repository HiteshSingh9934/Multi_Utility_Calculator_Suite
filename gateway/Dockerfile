FROM nginx:1.30-alpine

# NGINX_ENTRYPOINT_LOCAL_RESOLVERS: the official entrypoint reads the container's DNS
#   server from /etc/resolv.conf and passes it to the template as NGINX_LOCAL_RESOLVERS.
# DNS_SUFFIX: empty for Docker Compose; Kubernetes sets it to the cluster domain.
ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    DNS_SUFFIX=""

# Files in /etc/nginx/templates are rendered into /etc/nginx/conf.d at startup
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY html/ /usr/share/nginx/html/

# The charting library is 4.8 MB. Compress it once here (to about 1.5 MB) so nginx's
# gzip_static can send the .gz copy instead of compressing it again for every visitor.
RUN gzip -9 -c /usr/share/nginx/html/vendor/plotly.min.js > /usr/share/nginx/html/vendor/plotly.min.js.gz

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1/healthz"]

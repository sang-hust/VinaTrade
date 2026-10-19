# Static hosting for the Flutter web build (Railway service "vinatrade-web").
# The build itself is produced locally by app/deploy/deploy_web.sh and copied next to this file as ./site.
FROM nginx:1.27-alpine
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY site/ /usr/share/nginx/html/
ENV PORT=8080
EXPOSE 8080

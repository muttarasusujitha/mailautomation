FROM nginx:1.25-alpine
COPY microservices/gateway/nginx.conf /etc/nginx/nginx.conf
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
  CMD wget -q --spider http://127.0.0.1/health || exit 1
CMD ["nginx", "-g", "daemon off;"]

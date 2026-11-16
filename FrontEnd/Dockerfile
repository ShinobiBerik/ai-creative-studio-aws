# Lightweight static web server for the 4-in-1 AI Creative Studio SPA
FROM nginx:alpine

# Copy the zero-secret SPA bundle into the Nginx public root
COPY index.html /usr/share/nginx/html/index.html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]

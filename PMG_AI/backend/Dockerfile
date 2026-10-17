# Node API gateway image. Build context = PMG_AI/backend/
FROM node:22-alpine
ENV NODE_ENV=production PORT=4000 LOG_DIR=/var/pmg/logs UPLOAD_DIR=/var/pmg/uploads DATA_DIR=/var/pmg/data
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY src/ src/
RUN mkdir -p /var/pmg/logs /var/pmg/uploads /var/pmg/data && chown -R node:node /var/pmg
USER node
EXPOSE 4000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s \
  CMD node -e "fetch('http://127.0.0.1:4000/api/health').then(r=>process.exit(r.status<500?0:1)).catch(()=>process.exit(1))"
CMD ["node", "src/server.js"]

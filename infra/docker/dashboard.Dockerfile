FROM node:20-slim AS base

WORKDIR /srv

COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm install

COPY dashboard/ ./

EXPOSE 3000
CMD ["npm", "run", "dev"]

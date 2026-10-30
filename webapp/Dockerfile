# boasi_s webapp — React + Vite (dev-сервер внутри Docker)
FROM node:20-alpine

WORKDIR /app

# Ставим зависимости first (кеш слоя не инвалидируется при изменении кода)
COPY package.json package-lock.json ./
RUN npm install

COPY . .

EXPOSE 5173

# В docker-compose передаётся VITE_API_TARGET=http://backend:8000
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

FROM node:22-alpine

WORKDIR /app

COPY package*.json ./
RUN npm ci --legacy-peer-deps

COPY . .

EXPOSE 5174

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

#############################
# 1️⃣ Build Stage
#############################
FROM node:20-alpine AS builder
WORKDIR /app

# Copiamos manifest primero para aprovechar la cache
COPY ./package*.json ./

# Instalamos dependencias de forma determinista
RUN npm ci --legacy-peer-deps

# Copiamos el código
COPY ./ ./

# 🔐 Env DUMMY para que Next.js no falle en el build.
ENV MONGODB_URI="mongodb://placeholder" \
    DATABASE_NAME="placeholder" \
    COLLECTION_NAME="placeholder" \
    DATAWORKZ_SERVICE="https://placeholder" \
    DATAWORKZ_TOKEN="placeholder" \
    DATAWORKZ_AGENT_ID="placeholder" \
    DATAWORKZ_LLM_ID="placeholder"


RUN npm run build

#############################
# 2️⃣ Runtime Stage
#############################
FROM node:20-alpine
WORKDIR /app

# Copy only what the runtime needs from the builder
COPY --from=builder /app ./

# Container Apps expects the app on 8080
ENV PORT=8080
EXPOSE 8080

# Runtime env vars are injected by the hosting platform
CMD ["npm", "start"]

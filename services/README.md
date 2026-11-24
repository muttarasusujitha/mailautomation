# TrainerSync Microservices

This directory contains the first extracted services for the microservice-based version of TrainerSync.

## Services

- `api-gateway`: single entry point for frontend API calls. It routes Google auth to `auth-service` and routes the rest to the existing backend while migration continues.
- `auth-service`: owns Google login and stores authenticated users in MongoDB.
- `domain-proxy`: reusable FastAPI microservice shell used for domain services while business logic is extracted from the legacy backend.

## Domain Service Containers

`docker-compose.microservices.yml` starts these domain services:

- `trainer-service`
- `requirement-service`
- `email-service`
- `ai-service`
- `notification-service`
- `document-service`
- `interview-service`
- `admin-service`

The existing `backend` app remains available as `legacy-backend` in the microservice compose file. Domain services proxy to it during migration, and business logic can be moved into each service one capability at a time.

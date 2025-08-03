dev:
	cd app && npm run dev

build:
	docker compose -f docker-compose.dev.yaml build

up:
	docker compose -f docker-compose.dev.yaml up

up-infra:
	docker compose -f docker-compose.dev-infra.yaml up

down-infra:
	docker compose -f docker-compose.dev-infra.yaml down -v

restart:
	docker compose -f docker-compose.dev.yaml up -d

down-clean:
	docker compose -f docker-compose.dev.yaml down -v

down:
	docker compose -f docker-compose.dev.yaml down

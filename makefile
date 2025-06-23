dev:
	cd app && npm run dev

build:
	docker compose -f docker-compose.dev.yaml build

up:
	docker compose -f docker-compose.dev.yaml up

restart:
	docker compose -f docker-compose.dev.yaml up -d

down:
	docker compose -f docker-compose.dev.yaml down -v

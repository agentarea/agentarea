dev:
	cd app && npm run dev

build:
	docker compose -f docker-compose.dev.yaml build

up:
	docker compose -f docker-compose.dev.yaml up

down:
	docker compose -f docker-compose.dev.yaml down -v

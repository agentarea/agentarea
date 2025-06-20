dev:
	cd app && npm run dev

up:
	docker compose -f docker-compose.dev.yaml up --build

restart:
	docker compose -f docker-compose.dev.yaml up -d

down:
	docker compose -f docker-compose.dev.yaml down -v

.PHONY: build run test tidy

build:
	go build -o bin/event-service ./cmd/server

run:
	go run ./cmd/server

test:
	go test ./...

tidy:
	go mod tidy

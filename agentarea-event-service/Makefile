.PHONY: check build run test lint tidy

# CI installs the same version (.github/workflows/ci.yml); keep both in step.
GOLANGCI_LINT_VERSION := v2.15.0

check:
	go build ./...
	go test ./...
	$(MAKE) lint

build:
	go build -o bin/event-service ./cmd/server

run:
	go run ./cmd/server

test:
	go test ./...

lint:
	@bash ../scripts/require-golangci-lint.sh $(GOLANGCI_LINT_VERSION)
	golangci-lint run

tidy:
	go mod tidy

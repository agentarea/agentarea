.PHONY: check build test lint

# CI installs the same version (.github/workflows/ci.yml); keep both in step.
GOLANGCI_LINT_VERSION := v2.12.2

check: build test lint

build:
	go build ./...

test:
	go test ./...

lint:
	@bash ../scripts/require-golangci-lint.sh $(GOLANGCI_LINT_VERSION)
	golangci-lint run

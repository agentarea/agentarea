GOLANGCI_LINT ?= golangci-lint
GOLANGCI_LINT_VERSION := 2.15.0
export GOTOOLCHAIN ?= auto

check: archlint-fresh openapi-fresh build vet test lint-version lint archlint-proof tableowner connections-deps

build:
	go build ./...
	go build -tags archviolation ./...

vet:
	go vet ./...

test:
	go test -race ./...

lint-version:
	@$(GOLANGCI_LINT) version | grep -q "version $(GOLANGCI_LINT_VERSION) " || \
		{ echo "golangci-lint $(GOLANGCI_LINT_VERSION) required, found: $$($(GOLANGCI_LINT) version)"; exit 1; }

lint:
	$(GOLANGCI_LINT) run ./...

# The committed .golangci.yml is what tools/archgen prints.
archlint-fresh:
	go run ./tools/archgen | diff -u .golangci.yml -

# The fixtures tagged archviolation hold deliberate violations ("// want <linter>")
# and allowed imports ("// allowed"); the lint must report exactly the former.
archlint-proof:
	go run ./tools/archproof -lint $(GOLANGCI_LINT)

# Decision 3a: a module's queries name only the tables it owns.
tableowner:
	go run ./tools/tableowner -owners tools/tableowner/owners.csv internal/modules

# Decision 7: connections links no other module's internals (kept for `agentarea mcp --standalone`).
connections-deps:
	@out="$$(go list -deps ./internal/modules/connections/... | grep /internal/modules/ | grep -v -E '/internal/modules/(connections(/|$$)|[a-z]+/api$$)')"; \
		test -z "$$out" || { echo "connections imports other modules' internals:"; echo "$$out"; exit 1; }

# Decision 13: api/openapi is generated from the Python-exported spec (needs network once for oapi-codegen v2.8.2).
generate:
	go run ./tools/openapigen

openapi-fresh:
	go run ./tools/openapigen -check

archgen:
	go run ./tools/archgen > .golangci.yml

.PHONY: generate openapi-fresh check build vet test lint-version lint archlint-fresh archlint-proof tableowner connections-deps archgen

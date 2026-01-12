# Shelf - Book Digitization Pipeline
# Go implementation

ifndef VERBOSE
MAKEFLAGS+=--no-print-directory
endif

# Provide info from git to the version package using linker flags.
ifeq (, $(shell which git))
$(error "No git in $(PATH), version information won't be included")
else
VERSION_GOINFO=$(shell go version)
VERSION_GITCOMMIT=$(shell git rev-parse HEAD 2>/dev/null || echo "unknown")
VERSION_GITCOMMITDATE=$(shell git show -s --format=%cs HEAD 2>/dev/null || echo "unknown")
ifneq ($(shell git symbolic-ref -q --short HEAD 2>/dev/null),main)
VERSION_GITRELEASE=dev-$(shell git symbolic-ref -q --short HEAD 2>/dev/null || echo "unknown")
else
VERSION_GITRELEASE=$(shell git describe --tags 2>/dev/null || echo "v0.0.0")
endif

$(info ----------------------------------------)
$(info GOINFO = $(VERSION_GOINFO))
$(info GITCOMMIT = $(VERSION_GITCOMMIT))
$(info GITCOMMITDATE = $(VERSION_GITCOMMITDATE))
$(info GITRELEASE = $(VERSION_GITRELEASE))
$(info ----------------------------------------)

BUILD_FLAGS=-trimpath -ldflags "\
-X 'github.com/jackzampolin/shelf/version.GoInfo=$(VERSION_GOINFO)'\
-X 'github.com/jackzampolin/shelf/version.GitRelease=$(VERSION_GITRELEASE)'\
-X 'github.com/jackzampolin/shelf/version.GitCommit=$(VERSION_GITCOMMIT)'\
-X 'github.com/jackzampolin/shelf/version.GitCommitDate=$(VERSION_GITCOMMITDATE)'"
endif

BINARY_NAME=shelf
TEST_FLAGS=-race -shuffle=on -timeout 5m

.PHONY: default
default: build

#
# Build targets
#

.PHONY: build
build: web
	go build $(BUILD_FLAGS) -o build/$(BINARY_NAME) ./cmd/shelf

.PHONY: build\:backend
build\:backend:
	go build $(BUILD_FLAGS) -o build/$(BINARY_NAME) ./cmd/shelf

.PHONY: install
install: web
	go install $(BUILD_FLAGS) ./cmd/shelf

.PHONY: install\:backend
install\:backend:
	go install $(BUILD_FLAGS) ./cmd/shelf

.PHONY: run
run:
	@$(MAKE) build
	./build/$(BINARY_NAME)

#
# Test targets
#

.PHONY: test
test:
	go test ./... $(TEST_FLAGS) -short

.PHONY: test\:all
test\:all:
	go test ./... $(TEST_FLAGS)

.PHONY: test\:verbose
test\:verbose:
	go test ./... $(TEST_FLAGS) -v

.PHONY: test\:coverage
test\:coverage:
	go test ./... $(TEST_FLAGS) -coverprofile=coverage.out -covermode=atomic
	go tool cover -html=coverage.out -o coverage.html

#
# Dependencies
#

.PHONY: deps
deps:
	go mod download
	go mod tidy

.PHONY: deps\:lint
deps\:lint:
	go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@latest

#
# Lint targets
#

.PHONY: lint
lint:
	golangci-lint run ./...

.PHONY: lint\:fix
lint\:fix:
	golangci-lint run ./... --fix

#
# Clean targets
#

.PHONY: clean
clean:
	rm -rf build/
	go clean

.PHONY: clean\:test
clean\:test:
	go clean -testcache

.PHONY: clean\:coverage
clean\:coverage:
	rm -f coverage.out coverage.html

#
# Utility targets
#

.PHONY: tidy
tidy:
	go mod tidy

.PHONY: verify
verify:
	@if go mod verify | grep -q 'all modules verified'; then \
		echo "Success!"; \
	else \
		echo "Failure:"; \
		go mod verify; \
		exit 2; \
	fi

.PHONY: fmt
fmt:
	go fmt ./...

#
# Help
#

#
# OpenAPI / Swagger targets
#

.PHONY: swagger
swagger:
	@echo "Generating OpenAPI spec..."
	swag init -g cmd/shelf/serve.go -o docs/swagger --parseDependency --parseInternal

.PHONY: swagger\:install
swagger\:install:
	go install github.com/swaggo/swag/cmd/swag@latest

.PHONY: swagger\:fmt
swagger\:fmt:
	swag fmt

#
# Frontend targets
#

WEB_DIR=web

.PHONY: web
web:
	cd $(WEB_DIR) && bun install && bun run build

.PHONY: web\:dev
web\:dev:
	cd $(WEB_DIR) && bun run dev

.PHONY: web\:install
web\:install:
	cd $(WEB_DIR) && bun install

.PHONY: web\:lint
web\:lint:
	cd $(WEB_DIR) && bun run lint

.PHONY: web\:clean
web\:clean:
	rm -rf $(WEB_DIR)/dist $(WEB_DIR)/node_modules

.PHONY: web\:types
web\:types:
	@echo "Generating TypeScript types from OpenAPI spec..."
	cd $(WEB_DIR) && bun run generate:types

.PHONY: web\:test
web\:test:
	cd $(WEB_DIR) && bun run test

.PHONY: web\:test\:integration
web\:test\:integration:
	@echo "Running web integration tests (requires backend running)..."
	cd $(WEB_DIR) && bun run test:integration

.PHONY: web\:test\:watch
web\:test\:watch:
	cd $(WEB_DIR) && bun run test:watch

#
# Combined targets
#

.PHONY: all
all: swagger web build
	@echo "Build complete! Run './build/shelf serve' to start."

.PHONY: dev
dev: swagger build\:backend
	@echo "Backend ready. Run 'make web:dev' in another terminal for frontend."

#
# Help
#

.PHONY: help
help:
	@echo "Shelf - Book Digitization Pipeline"
	@echo ""
	@echo "Build:"
	@echo "  make build              Build frontend + shelf binary (production)"
	@echo "  make build:backend      Build shelf binary only (for dev)"
	@echo "  make install            Install shelf with embedded frontend"
	@echo "  make install:backend    Install shelf without frontend rebuild"
	@echo "  make run                Build and run shelf"
	@echo "  make all                Build swagger + frontend + backend"
	@echo "  make dev                Build backend only for development"
	@echo ""
	@echo "Test:"
	@echo "  make test               Run tests (skips integration tests)"
	@echo "  make test:all           Run all tests including integration"
	@echo "  make test:verbose       Run tests with verbose output"
	@echo "  make test:coverage      Run tests with coverage report"
	@echo ""
	@echo "OpenAPI:"
	@echo "  make swagger            Generate OpenAPI spec from code"
	@echo "  make swagger:install    Install swag CLI tool"
	@echo "  make swagger:fmt        Format swag annotations"
	@echo ""
	@echo "Frontend:"
	@echo "  make web                Build frontend for production"
	@echo "  make web:dev            Start frontend dev server"
	@echo "  make web:install        Install frontend dependencies"
	@echo "  make web:lint           Run frontend linter"
	@echo "  make web:types          Generate TypeScript types from OpenAPI"
	@echo "  make web:test           Run frontend unit tests"
	@echo "  make web:test:integration  Run frontend API integration tests"
	@echo "  make web:test:watch     Run frontend tests in watch mode"
	@echo "  make web:clean          Clean frontend build artifacts"
	@echo ""
	@echo "Development:"
	@echo "  make deps               Download and tidy dependencies"
	@echo "  make deps:lint          Install golangci-lint"
	@echo "  make lint               Run linter"
	@echo "  make lint:fix           Run linter with auto-fix"
	@echo "  make fmt                Format code"
	@echo "  make tidy               Run go mod tidy"
	@echo "  make verify             Verify module dependencies"
	@echo ""
	@echo "Clean:"
	@echo "  make clean              Remove build artifacts"
	@echo "  make clean:test         Clear test cache"
	@echo "  make clean:coverage     Remove coverage files"

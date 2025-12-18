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
build:
	go build $(BUILD_FLAGS) -o build/$(BINARY_NAME) ./cmd/shelf

.PHONY: install
install:
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

.PHONY: help
help:
	@echo "Shelf - Book Digitization Pipeline"
	@echo ""
	@echo "Build:"
	@echo "  make build              Build the shelf binary"
	@echo "  make install            Install shelf"
	@echo "  make run                Build and run shelf"
	@echo ""
	@echo "Test:"
	@echo "  make test               Run tests (skips integration tests)"
	@echo "  make test:all           Run all tests including integration"
	@echo "  make test:verbose       Run tests with verbose output"
	@echo "  make test:coverage      Run tests with coverage report"
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

package common

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

func TestLoadTocEntriesRejectsGraphQLErrorInsteadOfTreatingItAsEmpty(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":{"TocEntry":null},"errors":[{"message":"Cannot query field link_retries on type TocEntry"}]}`))
	}))
	defer server.Close()

	ctx := svcctx.WithServices(context.Background(), &svcctx.Services{
		DefraClient: defra.NewClient(server.URL),
	})
	entries, err := LoadTocEntries(ctx, "toc-1")
	if err == nil || !strings.Contains(err.Error(), "link_retries") {
		t.Fatalf("LoadTocEntries entries=%v error=%v, want GraphQL schema error", entries, err)
	}
}

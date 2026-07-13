package endpoints

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

func TestGetBookExposesDurableParseCertification(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"data":{"Book":[{"_docID":"book-1","title":"Book","status":"complete","status_reason":"","metadata_complete":true,"structure_complete":true,"structure_failed":false,"page_count":42}]}}`)
	}))
	defer server.Close()

	ctx := svcctx.WithServices(context.Background(), &svcctx.Services{
		DefraClient: defra.NewClient(server.URL),
	})
	req := httptest.NewRequest(http.MethodGet, "/api/books/book-1", nil).WithContext(ctx)
	req.SetPathValue("id", "book-1")
	w := httptest.NewRecorder()
	(&GetBookEndpoint{}).handler(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d; body=%s", w.Code, w.Body.String())
	}
	var book Book
	if err := json.NewDecoder(w.Body).Decode(&book); err != nil {
		t.Fatal(err)
	}
	if !book.MetadataComplete || !book.StructureComplete || book.StructureFailed {
		t.Fatalf("durable parse state not exposed: %#v", book)
	}
}

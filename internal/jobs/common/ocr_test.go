package common

import (
	"context"
	"encoding/base64"
	"os"
	"testing"

	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/providers"
)

func TestSaveExtractedImagesWritesURLAndStripsBase64(t *testing.T) {
	homeDir, err := home.New(t.TempDir())
	if err != nil {
		t.Fatalf("home.New() error = %v", err)
	}

	imageData := []byte("jpeg bytes")
	result := &providers.OCRResult{
		Text: "![Map](img-1.jpg)",
		Metadata: map[string]any{
			"images": []map[string]any{{
				"id":           "img-1.jpg",
				"has_base64":   true,
				"image_base64": "data:image/jpeg;base64," + base64.StdEncoding.EncodeToString(imageData),
			}},
		},
	}

	text := SaveExtractedImages(context.Background(), homeDir, "book 1", 4, result)
	wantURL := "/api/books/book%201/pages/4/extracted-images/img-1.jpg"
	if text != "![Map]("+wantURL+")" {
		t.Fatalf("updated text = %q, want image URL", text)
	}

	saved, err := os.ReadFile(homeDir.ExtractedImagePath("book 1", 4, "img-1.jpg"))
	if err != nil {
		t.Fatalf("expected saved image: %v", err)
	}
	if string(saved) != string(imageData) {
		t.Fatalf("saved image bytes = %q, want %q", saved, imageData)
	}

	images := result.Metadata["images"].([]map[string]any)
	if _, ok := images[0]["image_base64"]; ok {
		t.Fatalf("image_base64 should be stripped before persistence: %#v", images[0])
	}
	if hasBase64, _ := images[0]["has_base64"].(bool); hasBase64 {
		t.Fatalf("has_base64 should be false after persistence prep: %#v", images[0])
	}
	if images[0]["url"] != wantURL {
		t.Fatalf("metadata url = %v, want %s", images[0]["url"], wantURL)
	}
}

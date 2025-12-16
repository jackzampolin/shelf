package providers

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestMistralOCRClient_ProcessImage(t *testing.T) {
	t.Run("successful OCR", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			// Verify request
			if r.URL.Path != "/ocr" {
				t.Errorf("unexpected path: %s", r.URL.Path)
			}
			if r.Method != "POST" {
				t.Errorf("unexpected method: %s", r.Method)
			}
			if ct := r.Header.Get("Content-Type"); ct != "application/json" {
				t.Errorf("unexpected content-type: %s", ct)
			}
			if auth := r.Header.Get("Authorization"); auth != "Bearer test-key" {
				t.Errorf("unexpected authorization: %s", auth)
			}

			// Return mock response
			resp := mistralOCRResponse{
				Model: "mistral-ocr-latest",
				Pages: []mistralOCRPage{
					{
						Index:    0,
						Markdown: "# Chapter 1\n\nThis is the extracted text.",
						Images: []mistralOCRImage{
							{
								ID:           "img-1",
								TopLeftX:     100,
								TopLeftY:     200,
								BottomRightX: 300,
								BottomRightY: 400,
							},
						},
						Dimensions: mistralPageDimensions{
							Width:  1700,
							Height: 2200,
							DPI:    300,
						},
					},
				},
				UsageInfo: &mistralUsageInfo{
					PagesProcessed: 1,
					DocSizeBytes:   12345,
				},
			}

			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(resp)
		}))
		defer server.Close()

		client := NewMistralOCRClient(MistralOCRConfig{
			APIKey:  "test-key",
			BaseURL: server.URL,
		})

		result, err := client.ProcessImage(context.Background(), []byte("fake image data"), 1)

		if err != nil {
			t.Fatalf("ProcessImage() error = %v", err)
		}
		if !result.Success {
			t.Error("expected Success = true")
		}
		if result.Text != "# Chapter 1\n\nThis is the extracted text." {
			t.Errorf("unexpected text: %q", result.Text)
		}
		if result.CostUSD != MistralOCRCostPerPage {
			t.Errorf("CostUSD = %f, want %f", result.CostUSD, MistralOCRCostPerPage)
		}
		if result.ExecutionTime == 0 {
			t.Error("expected non-zero ExecutionTime")
		}

		// Verify metadata
		if result.Metadata == nil {
			t.Fatal("expected metadata")
		}
		if result.Metadata["model_used"] != "mistral-ocr-latest" {
			t.Errorf("model_used = %v", result.Metadata["model_used"])
		}
		dims, ok := result.Metadata["dimensions"].(map[string]any)
		if !ok {
			t.Fatal("expected dimensions in metadata")
		}
		if dims["width"] != 1700 || dims["height"] != 2200 || dims["dpi"] != 300 {
			t.Errorf("unexpected dimensions: %v", dims)
		}
		images, ok := result.Metadata["images"].([]map[string]any)
		if !ok || len(images) != 1 {
			t.Fatalf("expected 1 image, got %v", result.Metadata["images"])
		}
		if images[0]["id"] != "img-1" {
			t.Errorf("unexpected image id: %v", images[0]["id"])
		}
	})

	t.Run("empty pages response", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			resp := mistralOCRResponse{
				Model: "mistral-ocr-latest",
				Pages: []mistralOCRPage{}, // Empty pages
			}
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(resp)
		}))
		defer server.Close()

		client := NewMistralOCRClient(MistralOCRConfig{
			APIKey:  "test-key",
			BaseURL: server.URL,
		})

		result, err := client.ProcessImage(context.Background(), []byte("fake"), 1)

		if err == nil {
			t.Error("expected error for empty pages")
		}
		if result.Success {
			t.Error("expected Success = false")
		}
		if result.ErrorMessage == "" {
			t.Error("expected error message")
		}
	})

	t.Run("API error response", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(map[string]any{
				"error": map[string]string{
					"message": "Invalid image format",
					"type":    "invalid_request_error",
				},
			})
		}))
		defer server.Close()

		client := NewMistralOCRClient(MistralOCRConfig{
			APIKey:  "test-key",
			BaseURL: server.URL,
		})

		result, err := client.ProcessImage(context.Background(), []byte("fake"), 1)

		if err == nil {
			t.Error("expected error for API error response")
		}
		if result.Success {
			t.Error("expected Success = false")
		}
	})

	t.Run("context cancellation", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			time.Sleep(100 * time.Millisecond)
			w.WriteHeader(http.StatusOK)
		}))
		defer server.Close()

		client := NewMistralOCRClient(MistralOCRConfig{
			APIKey:  "test-key",
			BaseURL: server.URL,
		})

		ctx, cancel := context.WithCancel(context.Background())
		cancel() // Cancel immediately

		result, err := client.ProcessImage(ctx, []byte("fake"), 1)

		if err == nil {
			t.Error("expected error from cancelled context")
		}
		if result.Success {
			t.Error("expected Success = false")
		}
	})

	t.Run("include images option", func(t *testing.T) {
		var receivedIncludeImages bool
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			var req mistralOCRRequest
			json.NewDecoder(r.Body).Decode(&req)
			receivedIncludeImages = req.IncludeImageBase64

			resp := mistralOCRResponse{
				Model: "mistral-ocr-latest",
				Pages: []mistralOCRPage{{
					Index:      0,
					Markdown:   "text",
					Dimensions: mistralPageDimensions{Width: 100, Height: 100, DPI: 72},
				}},
			}
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(resp)
		}))
		defer server.Close()

		client := NewMistralOCRClient(MistralOCRConfig{
			APIKey:        "test-key",
			BaseURL:       server.URL,
			IncludeImages: true,
		})

		_, err := client.ProcessImage(context.Background(), []byte("fake"), 1)
		if err != nil {
			t.Fatalf("ProcessImage() error = %v", err)
		}

		if !receivedIncludeImages {
			t.Error("expected include_image_base64 to be true in request")
		}
	})
}

// TestMistralOCRIntegration runs real OCR against the Mistral API.
// Requires MISTRAL_API_KEY environment variable to be set.
// Uses test fixtures from testdata/ directory.
func TestMistralOCRIntegration(t *testing.T) {
	apiKey := os.Getenv("MISTRAL_API_KEY")
	if apiKey == "" {
		t.Skip("MISTRAL_API_KEY not set - skipping integration test")
	}

	client := NewMistralOCRClient(MistralOCRConfig{
		APIKey: apiKey,
	})

	// Find test images
	testdataDir := filepath.Join("testdata")
	entries, err := os.ReadDir(testdataDir)
	if err != nil {
		t.Skipf("testdata directory not found: %v", err)
	}

	var testImages []string
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), ".png") {
			testImages = append(testImages, filepath.Join(testdataDir, e.Name()))
		}
	}

	if len(testImages) == 0 {
		t.Skip("no test images found in testdata/")
	}

	t.Run("real OCR", func(t *testing.T) {
		// Just test one image to minimize cost
		imagePath := testImages[0]
		imageData, err := os.ReadFile(imagePath)
		if err != nil {
			t.Fatalf("failed to read test image: %v", err)
		}

		t.Logf("Testing OCR on %s (%d bytes)", filepath.Base(imagePath), len(imageData))

		ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
		defer cancel()

		result, err := client.ProcessImage(ctx, imageData, 1)
		if err != nil {
			t.Fatalf("ProcessImage() error = %v", err)
		}

		// Verify success
		if !result.Success {
			t.Errorf("OCR failed: %s", result.ErrorMessage)
		}

		// Verify we got text
		if len(result.Text) == 0 {
			t.Error("expected non-empty text")
		}
		t.Logf("Extracted %d characters", len(result.Text))

		// Log first 500 chars of output
		preview := result.Text
		if len(preview) > 500 {
			preview = preview[:500] + "..."
		}
		t.Logf("Text preview:\n%s", preview)

		// Verify cost tracking
		if result.CostUSD <= 0 {
			t.Error("expected positive cost")
		}
		t.Logf("Cost: $%.4f", result.CostUSD)

		// Verify timing
		if result.ExecutionTime == 0 {
			t.Error("expected non-zero execution time")
		}
		t.Logf("Execution time: %v", result.ExecutionTime)

		// Verify metadata
		if result.Metadata == nil {
			t.Error("expected metadata")
		}
		if result.Metadata["model_used"] == nil {
			t.Error("expected model_used in metadata")
		}
		t.Logf("Model: %v", result.Metadata["model_used"])

		// Check dimensions
		dims, ok := result.Metadata["dimensions"].(map[string]any)
		if !ok {
			t.Error("expected dimensions in metadata")
		} else {
			t.Logf("Dimensions: %vx%v @ %v DPI", dims["width"], dims["height"], dims["dpi"])
		}
	})

	// Test multiple images if we want more thorough testing
	if testing.Verbose() && len(testImages) > 1 {
		t.Run("multiple images", func(t *testing.T) {
			var totalCost float64
			var totalTime time.Duration

			for i, imagePath := range testImages {
				if i >= 2 { // Limit to 2 images to control cost
					break
				}

				imageData, err := os.ReadFile(imagePath)
				if err != nil {
					t.Errorf("failed to read %s: %v", imagePath, err)
					continue
				}

				ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
				result, err := client.ProcessImage(ctx, imageData, i+1)
				cancel()

				if err != nil {
					t.Errorf("OCR failed for %s: %v", filepath.Base(imagePath), err)
					continue
				}

				totalCost += result.CostUSD
				totalTime += result.ExecutionTime
				t.Logf("Page %d (%s): %d chars, $%.4f, %v",
					i+1, filepath.Base(imagePath), len(result.Text), result.CostUSD, result.ExecutionTime)
			}

			t.Logf("Total: $%.4f, %v", totalCost, totalTime)
		})
	}
}

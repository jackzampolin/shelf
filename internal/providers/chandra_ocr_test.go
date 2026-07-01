package providers

import (
	"bytes"
	"context"
	"encoding/json"
	"image"
	"image/color"
	"image/png"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// chandraStub serves an OpenAI-compatible chat endpoint returning markdown,
// recording the chat request body so tests can assert the image was sent.
func chandraStub(t *testing.T, markdown string, capture *[]byte) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/models":
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`{"object":"list","data":[{"id":"chandra"}]}`))
		case "/chat/completions":
			if capture != nil {
				*capture, _ = io.ReadAll(r.Body)
			}
			resp := map[string]any{
				"id":    "x",
				"model": "datalab-to/chandra-ocr-2",
				"choices": []any{map[string]any{
					"message":       map[string]any{"role": "assistant", "content": markdown},
					"finish_reason": "stop",
				}},
				"usage": map[string]any{"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
			}
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(resp)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
}

func TestChandraOCRClient_ProcessImage(t *testing.T) {
	var body []byte
	srv := chandraStub(t, "# Chapter One\n\nSome text.", &body)
	defer srv.Close()

	c := NewChandraOCRClient(ChandraOCRConfig{BaseURLs: []string{srv.URL}})
	if c.Name() != ChandraOCRName {
		t.Fatalf("Name() = %q, want %q", c.Name(), ChandraOCRName)
	}

	res, err := c.ProcessImage(context.Background(), []byte("fake-jpeg-bytes"), 1)
	if err != nil {
		t.Fatalf("ProcessImage() error = %v", err)
	}
	if !res.Success {
		t.Fatalf("Success = false, err=%s", res.ErrorMessage)
	}
	if res.Text != "# Chapter One\n\nSome text." {
		t.Fatalf("Text = %q, want the markdown", res.Text)
	}
	if res.CostUSD != 0 {
		t.Fatalf("CostUSD = %v, want 0 for local OCR", res.CostUSD)
	}
	// The page image must be sent as an image_url part in the chat request.
	if !strings.Contains(string(body), "image_url") || !strings.Contains(string(body), "data:image") {
		t.Fatalf("chat request did not include the page image; body=%s", body)
	}
	for _, want := range []string{
		`"max_tokens":12384`,
		`"temperature":0`,
		`"top_p":0.1`,
		`OCR this image to HTML, arranged as layout blocks`,
	} {
		if !strings.Contains(string(body), want) {
			t.Fatalf("chat request missing %q; body=%s", want, body)
		}
	}
}

func TestChandraOCRClient_ProcessImageParsesLayoutHTML(t *testing.T) {
	raw := `<div data-bbox="100 20 800 60" data-label="Page-Header"><i>Running Header</i></div>
<div data-bbox="100 80 800 160" data-label="Section-Header"><h2>CHAPTER ONE</h2></div>
<div data-bbox="100 170 800 300" data-label="Text"><p>Body text<sup>1</sup> continues.</p></div>
<div data-bbox="100 320 300 520" data-label="Image"><img alt="Operational map"/></div>
<div data-bbox="100 900 800 940" data-label="Page-Footer">12</div>
<div data-bbox="0 0 1000 1000" data-label="Blank-Page"></div>`

	srv := chandraStub(t, raw, nil)
	defer srv.Close()

	c := NewChandraOCRClient(ChandraOCRConfig{
		BaseURLs:      []string{srv.URL},
		IncludeImages: true,
	})
	res, err := c.ProcessImage(context.Background(), testPNG(t), 3)
	if err != nil {
		t.Fatalf("ProcessImage() error = %v", err)
	}
	if strings.Contains(res.Text, "data-bbox") || strings.Contains(res.Text, "data-label") || strings.Contains(res.Text, "<div") {
		t.Fatalf("layout artifacts remained in markdown: %s", res.Text)
	}
	if strings.Contains(res.Text, "Running Header") || strings.Contains(res.Text, "\n12\n") {
		t.Fatalf("page header/footer leaked into markdown: %s", res.Text)
	}
	for _, want := range []string{"## CHAPTER ONE", "Body text<sup>1</sup> continues.", "![Operational map](chandra-page-0003-image-01.jpg)"} {
		if !strings.Contains(res.Text, want) {
			t.Fatalf("markdown missing %q: %s", want, res.Text)
		}
	}
	if res.Header != "Running Header" {
		t.Fatalf("Header = %q, want running header", res.Header)
	}
	if res.Footer != "12" {
		t.Fatalf("Footer = %q, want 12", res.Footer)
	}
	images, ok := res.Metadata["images"].([]map[string]any)
	if !ok || len(images) != 1 {
		t.Fatalf("metadata images = %#v, want one extracted image", res.Metadata["images"])
	}
	if images[0]["id"] != "chandra-page-0003-image-01.jpg" || images[0]["image_base64"] == "" {
		t.Fatalf("unexpected image metadata: %#v", images[0])
	}
}

func TestChandraOCRClient_ProcessImageCleansArtifacts(t *testing.T) {
	raw := `<div data-bbox="100 100 800 300" data-label="Table"><table><tbody><tr><td>PLANNING &#34;TORCH&#34;</td><td>83</td></tr><tr><td>GERMANY&#39;S FRONTIER</td><td>351</td></tr></tbody></table></div>
<div data-bbox="0 0 1000 1000" data-label="Image"><img alt="Blank white page"/></div>
<div data-bbox="100 320 400 360" data-label="Text"><p>Picture at<br/>page 18</p></div>`

	srv := chandraStub(t, raw, nil)
	defer srv.Close()

	c := NewChandraOCRClient(ChandraOCRConfig{
		BaseURLs:      []string{srv.URL},
		IncludeImages: true,
	})
	res, err := c.ProcessImage(context.Background(), testPNG(t), 7)
	if err != nil {
		t.Fatalf("ProcessImage() error = %v", err)
	}
	for _, bad := range []string{"&#34;", "&#39;", "Blank white page", "Picture at"} {
		if strings.Contains(res.Text, bad) {
			t.Fatalf("markdown contains artifact %q: %s", bad, res.Text)
		}
	}
	for _, want := range []string{`PLANNING "TORCH"`, "GERMANY'S FRONTIER"} {
		if !strings.Contains(res.Text, want) {
			t.Fatalf("markdown missing %q: %s", want, res.Text)
		}
	}
	images, ok := res.Metadata["images"].([]map[string]any)
	if !ok {
		t.Fatalf("metadata images = %#v, want image metadata slice", res.Metadata["images"])
	}
	if len(images) != 0 {
		t.Fatalf("blank image should not be extracted: %#v", images)
	}
}

func TestChandraOCRClient_HealthCheck(t *testing.T) {
	srv := chandraStub(t, "x", nil)
	defer srv.Close()
	c := NewChandraOCRClient(ChandraOCRConfig{BaseURLs: []string{srv.URL}})
	if err := c.HealthCheck(context.Background()); err != nil {
		t.Fatalf("HealthCheck() error = %v", err)
	}
}

func TestCreateOCRProvider_Chandra(t *testing.T) {
	srv := chandraStub(t, "x", nil)
	defer srv.Close()
	p := createOCRProvider(OCRProviderConfig{Type: "chandra", BaseURLs: []string{srv.URL}})
	if p == nil {
		t.Fatal("expected non-nil chandra OCR provider")
	}
	if err := p.HealthCheck(context.Background()); err != nil {
		t.Fatalf("HealthCheck() error = %v", err)
	}
}

var _ OCRProvider = (*ChandraOCRClient)(nil)

func testPNG(t *testing.T) []byte {
	t.Helper()
	img := image.NewRGBA(image.Rect(0, 0, 100, 100))
	for y := 0; y < 100; y++ {
		for x := 0; x < 100; x++ {
			img.Set(x, y, color.RGBA{R: uint8(x), G: uint8(y), B: 100, A: 255})
		}
	}
	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		t.Fatalf("failed to encode test image: %v", err)
	}
	return buf.Bytes()
}

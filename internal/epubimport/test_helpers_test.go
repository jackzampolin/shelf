package epubimport

import (
	"archive/zip"
	"os"
	"path/filepath"
	"testing"
)

func writeRawEPUB(t *testing.T, members map[string]string) string {
	t.Helper()
	filename := filepath.Join(t.TempDir(), "fixture.epub")
	file, err := os.Create(filename)
	if err != nil {
		t.Fatal(err)
	}
	zw := zip.NewWriter(file)
	for name, content := range members {
		w, err := zw.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := w.Write([]byte(content)); err != nil {
			t.Fatal(err)
		}
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
	return filename
}

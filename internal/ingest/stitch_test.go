package ingest

import (
	"image"
	"image/color"
	"image/png"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"testing"

	"github.com/pdfcpu/pdfcpu/pkg/api"
)

func TestGroupParts(t *testing.T) {
	input := []string{
		"/scans/book-10.pdf",
		"/scans/book-1.pdf",
		"/scans/notes.txt",
		"/scans/single.pdf",
		"/scans/volume_2.pdf",
		"/scans/volume_1.pdf",
	}

	got := GroupParts(input, nil)
	want := []BookParts{
		{Name: "book", Parts: []string{"/scans/book-1.pdf", "/scans/book-10.pdf"}},
		{Name: "single", Parts: []string{"/scans/single.pdf"}},
		{Name: "volume", Parts: []string{"/scans/volume_1.pdf", "/scans/volume_2.pdf"}},
	}

	if !reflect.DeepEqual(got, want) {
		t.Fatalf("GroupParts() = %#v, want %#v", got, want)
	}
}

func TestGroupParts_CustomPattern(t *testing.T) {
	pattern := regexp.MustCompile(` part ([0-9]+)$`)
	input := []string{
		"/scans/Story part 2.pdf",
		"/scans/Story part 1.pdf",
	}

	got := GroupParts(input, pattern)
	want := []BookParts{
		{Name: "Story", Parts: []string{"/scans/Story part 1.pdf", "/scans/Story part 2.pdf"}},
	}

	if !reflect.DeepEqual(got, want) {
		t.Fatalf("GroupParts() = %#v, want %#v", got, want)
	}
}

func TestGroupParts_UnnumberedDoesNotJoinNumberedGroup(t *testing.T) {
	input := []string{
		"/scans/book.pdf",
		"/scans/book-1.pdf",
		"/scans/book-2.pdf",
	}

	got := GroupParts(input, nil)
	if len(got) != 2 {
		t.Fatalf("got %d groups, want 2: %#v", len(got), got)
	}
	if !reflect.DeepEqual(got[0].Parts, []string{"/scans/book-1.pdf", "/scans/book-2.pdf"}) {
		t.Fatalf("numbered group parts = %#v", got[0].Parts)
	}
	if !reflect.DeepEqual(got[1].Parts, []string{"/scans/book.pdf"}) {
		t.Fatalf("single group parts = %#v", got[1].Parts)
	}
}

func TestStitchPDF_PageCountIsSum(t *testing.T) {
	dir := t.TempDir()
	part1 := filepath.Join(dir, "part-1.pdf")
	part2 := filepath.Join(dir, "part-2.pdf")
	out := filepath.Join(dir, "stitched.pdf")

	createOnePagePDF(t, filepath.Join(dir, "img1.png"), part1, color.RGBA{R: 255, A: 255})
	createOnePagePDF(t, filepath.Join(dir, "img2.png"), part2, color.RGBA{B: 255, A: 255})

	if err := StitchPDF([]string{part1, part2}, out); err != nil {
		t.Fatalf("StitchPDF() error = %v", err)
	}

	count, err := api.PageCountFile(out)
	if err != nil {
		t.Fatalf("PageCountFile() error = %v", err)
	}
	if count != 2 {
		t.Fatalf("page count = %d, want 2", count)
	}
}

func createOnePagePDF(t *testing.T, imgPath, pdfPath string, c color.RGBA) {
	t.Helper()

	img := image.NewRGBA(image.Rect(0, 0, 8, 8))
	for y := 0; y < 8; y++ {
		for x := 0; x < 8; x++ {
			img.SetRGBA(x, y, c)
		}
	}

	f, err := os.Create(imgPath)
	if err != nil {
		t.Fatalf("create image: %v", err)
	}
	if err := png.Encode(f, img); err != nil {
		f.Close()
		t.Fatalf("encode image: %v", err)
	}
	if err := f.Close(); err != nil {
		t.Fatalf("close image: %v", err)
	}

	if err := api.ImportImagesFile([]string{imgPath}, pdfPath, nil, nil); err != nil {
		t.Fatalf("ImportImagesFile() error = %v", err)
	}
}

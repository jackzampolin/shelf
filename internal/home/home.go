package home

import (
	"fmt"
	"os"
	"path/filepath"
)

const (
	// DefaultDirName is the default name for the shelf home directory.
	DefaultDirName = ".shelf"

	// DataDirName is the subdirectory for book data and scans.
	DataDirName = "data"

	// ConfigFileName is the default config file name.
	ConfigFileName = "config.yaml"
)

// Dir represents the shelf home directory structure.
type Dir struct {
	path string
}

// New creates a new Dir with the given path.
// If path is empty, uses the default (~/.shelf).
func New(path string) (*Dir, error) {
	if path == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return nil, fmt.Errorf("failed to get user home directory: %w", err)
		}
		path = filepath.Join(home, DefaultDirName)
	}

	return &Dir{path: path}, nil
}

// Path returns the root path of the home directory.
func (d *Dir) Path() string {
	return d.path
}

// DataPath returns the path to the data directory.
func (d *Dir) DataPath() string {
	return filepath.Join(d.path, DataDirName)
}

// ConfigPath returns the path to the default config file.
func (d *Dir) ConfigPath() string {
	return filepath.Join(d.path, ConfigFileName)
}

// EnsureExists creates the home directory and subdirectories if they don't exist.
func (d *Dir) EnsureExists() error {
	// Create data directory (this also creates the parent)
	if err := os.MkdirAll(d.DataPath(), 0o755); err != nil {
		return fmt.Errorf("failed to create data directory: %w", err)
	}
	return nil
}

// Exists returns true if the home directory exists.
func (d *Dir) Exists() bool {
	_, err := os.Stat(d.path)
	return err == nil
}

// ConfigExists returns true if the config file exists in the home directory.
func (d *Dir) ConfigExists() bool {
	_, err := os.Stat(d.ConfigPath())
	return err == nil
}

// SourceImagesDir returns the directory for source images of a book.
func (d *Dir) SourceImagesDir(bookID string) string {
	return filepath.Join(d.path, "source_images", bookID)
}

// SourceImagePath returns the path to a specific page image.
// Page numbers are 1-indexed.
func (d *Dir) SourceImagePath(bookID string, pageNum int) string {
	return filepath.Join(d.SourceImagesDir(bookID), fmt.Sprintf("page_%04d.png", pageNum))
}

// SourceImagePaths returns paths for all pages of a book.
func (d *Dir) SourceImagePaths(bookID string, pageCount int) []string {
	paths := make([]string, pageCount)
	for i := 1; i <= pageCount; i++ {
		paths[i-1] = d.SourceImagePath(bookID, i)
	}
	return paths
}

// EnsureSourceImagesDir creates the source images directory for a book.
func (d *Dir) EnsureSourceImagesDir(bookID string) error {
	return os.MkdirAll(d.SourceImagesDir(bookID), 0o755)
}

// OriginalsDir returns the directory for original PDF files of a book.
func (d *Dir) OriginalsDir(bookID string) string {
	return filepath.Join(d.SourceImagesDir(bookID), "originals")
}

// EnsureOriginalsDir creates the originals directory for a book's PDFs.
func (d *Dir) EnsureOriginalsDir(bookID string) error {
	return os.MkdirAll(d.OriginalsDir(bookID), 0o755)
}

// ExportsDir returns the directory for exported files (epub, etc.).
func (d *Dir) ExportsDir() string {
	return filepath.Join(d.path, "exports")
}

// AudioDir returns the directory for generated audio files.
func (d *Dir) AudioDir() string {
	return filepath.Join(d.path, "audio")
}

// BookAudioDir returns the audio directory for a specific book.
func (d *Dir) BookAudioDir(bookID string) string {
	return filepath.Join(d.AudioDir(), bookID)
}

// ChapterAudioDir returns the directory for a chapter's audio segments.
func (d *Dir) ChapterAudioDir(bookID string, chapterIdx int) string {
	return filepath.Join(d.BookAudioDir(bookID), fmt.Sprintf("chapter_%04d", chapterIdx))
}

// SegmentAudioPath returns the path for a paragraph audio segment.
func (d *Dir) SegmentAudioPath(bookID string, chapterIdx, paragraphIdx int, format string) string {
	return filepath.Join(
		d.ChapterAudioDir(bookID, chapterIdx),
		fmt.Sprintf("segment_%04d.%s", paragraphIdx, format),
	)
}

// ChapterAudioPath returns the path for a concatenated chapter audio file.
func (d *Dir) ChapterAudioPath(bookID string, chapterIdx int, format string) string {
	return filepath.Join(
		d.BookAudioDir(bookID),
		fmt.Sprintf("chapter_%04d.%s", chapterIdx, format),
	)
}

// EnsureBookAudioDir creates the audio directory for a book.
func (d *Dir) EnsureBookAudioDir(bookID string) error {
	return os.MkdirAll(d.BookAudioDir(bookID), 0o755)
}

// EnsureChapterAudioDir creates the audio directory for a chapter.
func (d *Dir) EnsureChapterAudioDir(bookID string, chapterIdx int) error {
	return os.MkdirAll(d.ChapterAudioDir(bookID, chapterIdx), 0o755)
}

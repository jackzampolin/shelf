// Package web provides embedded frontend assets for the Shelf application.
package web

import (
	"embed"
	"io/fs"
)

//go:embed all:dist
var distFS embed.FS

// DistFS returns the embedded frontend assets as a filesystem.
// The returned FS has "dist" as the root, so files are accessed directly
// (e.g., "index.html" not "dist/index.html").
func DistFS() (fs.FS, error) {
	return fs.Sub(distFS, "dist")
}

package common

import (
	"context"
)

// BookMetadata contains extracted book metadata.
// Populated by metadata extraction or lazy-loaded from DefraDB.
type BookMetadata struct {
	Title           string   `json:"title,omitempty"`
	Subtitle        string   `json:"subtitle,omitempty"`
	Author          string   `json:"author,omitempty"`
	Authors         []string `json:"authors,omitempty"`
	ISBN            string   `json:"isbn,omitempty"`
	LCCN            string   `json:"lccn,omitempty"`
	Publisher       string   `json:"publisher,omitempty"`
	PublicationYear int      `json:"publication_year,omitempty"`
	Language        string   `json:"language,omitempty"`
	Description     string   `json:"description,omitempty"`
	Subjects        []string `json:"subjects,omitempty"`
	CoverPage       int      `json:"cover_page,omitempty"` // Scan page number containing cover image
}

// GetBookMetadata returns the book metadata (thread-safe).
// Returns nil if metadata has not been extracted or loaded.
// Use GetBookMetadataWithLazyLoad for lazy loading from DB.
func (b *BookState) GetBookMetadata() *BookMetadata {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.bookMetadata
}

// SetBookMetadata sets the book metadata (thread-safe).
// Called after metadata extraction completes.
func (b *BookState) SetBookMetadata(metadata *BookMetadata) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.bookMetadata = metadata
	b.bookMetadataLoaded = true
}

// GetBookMetadataWithLazyLoad returns book metadata, loading from DB if needed (thread-safe).
// Requires context with DefraClient for DB queries.
// Returns nil if metadata is not available in DB.
func (b *BookState) GetBookMetadataWithLazyLoad(ctx context.Context) *BookMetadata {
	b.mu.RLock()
	if b.bookMetadataLoaded {
		meta := b.bookMetadata
		b.mu.RUnlock()
		return meta
	}
	b.mu.RUnlock()

	// Need to load from DB - upgrade to write lock
	b.mu.Lock()
	defer b.mu.Unlock()

	// Double-check after acquiring write lock
	if b.bookMetadataLoaded {
		return b.bookMetadata
	}

	// Load from DefraDB
	metadata, loaded := loadBookMetadataFromDB(ctx, b.BookID)
	if loaded {
		b.bookMetadata = metadata
		b.bookMetadataLoaded = true
	}
	return b.bookMetadata
}

// GetBookTitle returns the book title (thread-safe convenience accessor).
func (b *BookState) GetBookTitle() string {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.bookMetadata != nil {
		return b.bookMetadata.Title
	}
	return ""
}

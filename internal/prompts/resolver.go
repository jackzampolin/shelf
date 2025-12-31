package prompts

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
)

// Resolver resolves prompts with book-level overrides.
// Resolution order: BookPromptOverride > Embedded default
type Resolver struct {
	store    *Store
	embedded map[string]EmbeddedPrompt
	mu       sync.RWMutex
	logger   *slog.Logger
}

// NewResolver creates a new prompt resolver.
func NewResolver(store *Store, logger *slog.Logger) *Resolver {
	if logger == nil {
		logger = slog.Default()
	}
	return &Resolver{
		store:    store,
		embedded: make(map[string]EmbeddedPrompt),
		logger:   logger,
	}
}

// Register registers an embedded prompt.
// This should be called during initialization by each stage/agent.
func (r *Resolver) Register(prompt EmbeddedPrompt) {
	r.mu.Lock()
	defer r.mu.Unlock()

	// Compute hash if not provided
	if prompt.Hash == "" {
		prompt.Hash = HashText(prompt.Text)
	}

	// Extract variables if not provided
	if prompt.Variables == nil {
		prompt.Variables = ExtractVariables(prompt.Text)
	}

	r.embedded[prompt.Key] = prompt
	r.logger.Debug("registered embedded prompt", "key", prompt.Key, "vars", prompt.Variables)
}

// Resolve resolves a prompt for a specific book.
// Returns the book override if it exists, otherwise the embedded default.
func (r *Resolver) Resolve(ctx context.Context, key string, bookID string) (*ResolvedPrompt, error) {
	// Check for book override first
	if bookID != "" && r.store != nil {
		override, err := r.store.GetBookOverride(ctx, bookID, key)
		if err != nil {
			r.logger.Warn("failed to check book override", "key", key, "book_id", bookID, "error", err)
			// Fall through to embedded default
		} else if override != nil {
			return &ResolvedPrompt{
				Key:        key,
				Text:       override.Text,
				Variables:  ExtractVariables(override.Text),
				IsOverride: true,
				CID:        override.DocID,
			}, nil
		}
	}

	// Fall back to embedded default
	r.mu.RLock()
	embedded, ok := r.embedded[key]
	r.mu.RUnlock()

	if !ok {
		return nil, fmt.Errorf("prompt not found: %s", key)
	}

	// Get CID from DB if available
	var cid string
	if r.store != nil {
		if dbPrompt, err := r.store.Get(ctx, key); err == nil && dbPrompt != nil {
			cid = dbPrompt.DocID
		}
	}

	return &ResolvedPrompt{
		Key:        key,
		Text:       embedded.Text,
		Variables:  embedded.Variables,
		IsOverride: false,
		CID:        cid,
	}, nil
}

// GetEmbedded returns the embedded default for a key (no book resolution).
func (r *Resolver) GetEmbedded(key string) (*EmbeddedPrompt, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	p, ok := r.embedded[key]
	return &p, ok
}

// AllEmbedded returns all registered embedded prompts.
func (r *Resolver) AllEmbedded() []EmbeddedPrompt {
	r.mu.RLock()
	defer r.mu.RUnlock()

	result := make([]EmbeddedPrompt, 0, len(r.embedded))
	for _, p := range r.embedded {
		result = append(result, p)
	}
	return result
}

// SyncAll syncs all registered embedded prompts to the database.
func (r *Resolver) SyncAll(ctx context.Context) error {
	if r.store == nil {
		return fmt.Errorf("store not configured")
	}

	r.mu.RLock()
	prompts := make([]EmbeddedPrompt, 0, len(r.embedded))
	for _, p := range r.embedded {
		prompts = append(prompts, p)
	}
	r.mu.RUnlock()

	for _, p := range prompts {
		if err := r.store.SyncPrompt(ctx, p); err != nil {
			return fmt.Errorf("failed to sync prompt %s: %w", p.Key, err)
		}
	}

	r.logger.Info("synced all prompts to database", "count", len(prompts))
	return nil
}

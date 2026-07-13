package common

import (
	"context"

	"github.com/jackzampolin/shelf/internal/svcctx"
)

// ResolvePrompts resolves prompts for a book and stores them in BookState.
// Uses the PromptResolver from context if available, falls back to defaults.
func ResolvePrompts(ctx context.Context, book *BookState, keys []string, defaults func(string) string) error {
	resolver := svcctx.PromptResolverFrom(ctx)
	logger := svcctx.LoggerFrom(ctx)

	for _, key := range keys {
		var text string
		var cid string

		if resolver != nil {
			resolved, err := resolver.Resolve(ctx, key, book.BookID)
			if err != nil {
				if logger != nil {
					logger.Warn("failed to resolve prompt, using default",
						"key", key, "book_id", book.BookID, "error", err)
				}
				// Fall through to defaults
			} else {
				text = resolved.Text
				cid = resolved.CID
				if resolved.IsOverride && logger != nil {
					logger.Debug("using book-level prompt override",
						"key", key, "book_id", book.BookID)
				}
			}
		}

		// If we didn't get text from resolver, use defaults
		if text == "" && defaults != nil {
			text = defaults(key)
		}

		book.Prompts[key] = text
		book.PromptCIDs[key] = cid
	}

	return nil
}

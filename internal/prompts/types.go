// Package prompts provides prompt management with embedded defaults and book-level overrides.
//
// The package supports a hybrid model where:
//   - Embedded .tmpl files in code are the source of truth for defaults
//   - The Prompt collection in DefraDB mirrors these for UI/CID traceability
//   - BookPromptOverride allows per-book customization
//
// Resolution order for a specific book:
//  1. BookPromptOverride (per-book customization, if exists)
//  2. Embedded default (from .tmpl files in code)
//
// The Prompt collection mirrors embedded defaults and is used for:
//   - Web UI display (list/edit prompts)
//   - CID traceability (linking LLM calls to exact prompt versions)
package prompts

import (
	"time"
)

// Prompt represents a prompt definition synced from embedded files.
type Prompt struct {
	Key          string   `json:"key"`
	Text         string   `json:"text"`
	Description  string   `json:"description,omitempty"`
	Variables    []string `json:"variables,omitempty"`
	EmbeddedHash string   `json:"embedded_hash,omitempty"`
	DocID        string   `json:"_docID,omitempty"`
}

// BookPromptOverride represents a per-book prompt customization.
type BookPromptOverride struct {
	BookID    string    `json:"book_id"`
	PromptKey string    `json:"prompt_key"`
	Text      string    `json:"text"`
	Note      string    `json:"note,omitempty"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
	DocID     string    `json:"_docID,omitempty"`
}

// ResolvedPrompt is the result of resolving a prompt for a specific book.
type ResolvedPrompt struct {
	Key        string   `json:"key"`
	Text       string   `json:"text"`
	Variables  []string `json:"variables,omitempty"`
	IsOverride bool     `json:"is_override"` // true if from BookPromptOverride
	CID        string   `json:"cid"`         // DefraDB document CID for traceability
}

// EmbeddedPrompt represents a prompt loaded from an embedded .tmpl file.
type EmbeddedPrompt struct {
	Key         string   // Hierarchical key: stages.blend.system
	Text        string   // The prompt text (Go template)
	Description string   // Human-readable description
	Variables   []string // Extracted template variables
	Hash        string   // SHA256 hash of the text for change detection
}

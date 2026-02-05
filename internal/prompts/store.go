package prompts

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"regexp"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
)

// validKeyPattern matches valid prompt keys (alphanumeric with dots, underscores).
var validKeyPattern = regexp.MustCompile(`^[a-zA-Z][a-zA-Z0-9._]*$`)

// Store provides access to prompts in DefraDB with book-level resolution.
type Store struct {
	client *defra.Client
	logger *slog.Logger
}

// NewStore creates a new prompt store.
func NewStore(client *defra.Client, logger *slog.Logger) *Store {
	if logger == nil {
		logger = slog.Default()
	}
	return &Store{client: client, logger: logger}
}

// Get retrieves a prompt by key from the Prompt collection.
// This returns the synced version from DB, not the embedded default.
func (s *Store) Get(ctx context.Context, key string) (*Prompt, error) {
	if !validKeyPattern.MatchString(key) {
		return nil, fmt.Errorf("invalid prompt key: %s", key)
	}

	query := fmt.Sprintf(`{
		Prompt(filter: {key: {_eq: %q}}) {
			_docID
			key
			text
			description
			variables
			embedded_hash
		}
	}`, key)

	resp, err := s.client.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("query failed: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("graphql error: %s", errMsg)
	}

	prompts, err := parsePrompts(resp.Data)
	if err != nil {
		return nil, err
	}
	if len(prompts) == 0 {
		return nil, nil
	}
	return &prompts[0], nil
}

// List retrieves all prompts from the Prompt collection.
func (s *Store) List(ctx context.Context) ([]Prompt, error) {
	query := `{
		Prompt {
			_docID
			key
			text
			description
			variables
			embedded_hash
		}
	}`

	resp, err := s.client.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("query failed: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("graphql error: %s", errMsg)
	}

	return parsePrompts(resp.Data)
}

// GetBookOverride retrieves a book-specific prompt override.
func (s *Store) GetBookOverride(ctx context.Context, bookID, promptKey string) (*BookPromptOverride, error) {
	query := fmt.Sprintf(`{
		BookPromptOverride(filter: {book_id: {_eq: %q}, prompt_key: {_eq: %q}}) {
			_docID
			book_id
			prompt_key
			text
			note
			created_at
			updated_at
		}
	}`, bookID, promptKey)

	resp, err := s.client.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("query failed: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("graphql error: %s", errMsg)
	}

	overrides, err := parseBookOverrides(resp.Data)
	if err != nil {
		return nil, err
	}
	if len(overrides) == 0 {
		return nil, nil
	}
	return &overrides[0], nil
}

// ListBookOverrides retrieves all prompt overrides for a book.
func (s *Store) ListBookOverrides(ctx context.Context, bookID string) ([]BookPromptOverride, error) {
	query := fmt.Sprintf(`{
		BookPromptOverride(filter: {book_id: {_eq: %q}}) {
			_docID
			book_id
			prompt_key
			text
			note
			created_at
			updated_at
		}
	}`, bookID)

	resp, err := s.client.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("query failed: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("graphql error: %s", errMsg)
	}

	return parseBookOverrides(resp.Data)
}

// SetBookOverride creates or updates a book-specific prompt override.
func (s *Store) SetBookOverride(ctx context.Context, bookID, promptKey, text, note string) error {
	// Check if override already exists
	existing, err := s.GetBookOverride(ctx, bookID, promptKey)
	if err != nil {
		return err
	}

	now := time.Now()

	if existing != nil {
		// Update existing override
		mutation := fmt.Sprintf(`mutation {
			update_BookPromptOverride(docID: %q, input: {
				text: %q,
				note: %q,
				updated_at: %q
			}) {
				_docID
			}
		}`, existing.DocID, text, note, now.Format(time.RFC3339))

		resp, err := s.client.Query(ctx, mutation)
		if err != nil {
			return fmt.Errorf("update failed: %w", err)
		}
		if errMsg := resp.Error(); errMsg != "" {
			return fmt.Errorf("graphql error: %s", errMsg)
		}
	} else {
		// Create new override
		mutation := fmt.Sprintf(`mutation {
			create_BookPromptOverride(input: {
				book_id: %q,
				prompt_key: %q,
				text: %q,
				note: %q,
				created_at: %q,
				updated_at: %q
			}) {
				_docID
			}
		}`, bookID, promptKey, text, note, now.Format(time.RFC3339), now.Format(time.RFC3339))

		resp, err := s.client.Query(ctx, mutation)
		if err != nil {
			return fmt.Errorf("create failed: %w", err)
		}
		if errMsg := resp.Error(); errMsg != "" {
			return fmt.Errorf("graphql error: %s", errMsg)
		}
	}

	return nil
}

// ClearBookOverride removes a book-specific prompt override.
func (s *Store) ClearBookOverride(ctx context.Context, bookID, promptKey string) error {
	existing, err := s.GetBookOverride(ctx, bookID, promptKey)
	if err != nil {
		return err
	}
	if existing == nil {
		return nil // Nothing to delete
	}

	mutation := fmt.Sprintf(`mutation {
		delete_BookPromptOverride(docID: %q) {
			_docID
		}
	}`, existing.DocID)

	resp, err := s.client.Query(ctx, mutation)
	if err != nil {
		return fmt.Errorf("delete failed: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return fmt.Errorf("graphql error: %s", errMsg)
	}

	return nil
}

// SyncPrompt syncs an embedded prompt to the database.
// If the prompt doesn't exist, it's created.
// If it exists and the embedded hash matches, it's updated (auto-sync).
// If it exists but was manually edited (hash differs), it's left alone.
func (s *Store) SyncPrompt(ctx context.Context, embedded EmbeddedPrompt) error {
	existing, err := s.Get(ctx, embedded.Key)
	if err != nil {
		return err
	}

	varsJSON, _ := json.Marshal(embedded.Variables)

	if existing == nil {
		// Create new prompt
		mutation := fmt.Sprintf(`mutation {
			create_Prompt(input: {
				key: %q,
				text: %q,
				description: %q,
				variables: %s,
				embedded_hash: %q
			}) {
				_docID
			}
		}`, embedded.Key, embedded.Text, embedded.Description, varsJSON, embedded.Hash)

		resp, err := s.client.Query(ctx, mutation)
		if err != nil {
			return fmt.Errorf("create failed: %w", err)
		}
		if errMsg := resp.Error(); errMsg != "" {
			return fmt.Errorf("graphql error: %s", errMsg)
		}
		s.logger.Debug("synced new prompt", "key", embedded.Key)
	} else if existing.EmbeddedHash == HashText(existing.Text) {
		// Existing prompt matches its embedded hash - safe to auto-update
		if existing.Text != embedded.Text {
			mutation := fmt.Sprintf(`mutation {
				update_Prompt(docID: %q, input: {
					text: %q,
					description: %q,
					variables: %s,
					embedded_hash: %q
				}) {
					_docID
				}
			}`, existing.DocID, embedded.Text, embedded.Description, varsJSON, embedded.Hash)

			resp, err := s.client.Query(ctx, mutation)
			if err != nil {
				return fmt.Errorf("update failed: %w", err)
			}
			if errMsg := resp.Error(); errMsg != "" {
				return fmt.Errorf("graphql error: %s", errMsg)
			}
			s.logger.Debug("auto-updated prompt from code", "key", embedded.Key)
		}
	} else {
		// Existing prompt was manually edited - don't overwrite
		s.logger.Debug("prompt was manually edited, skipping auto-sync",
			"key", embedded.Key,
			"db_hash", existing.EmbeddedHash,
			"current_hash", HashText(existing.Text))
	}

	return nil
}

// parsePrompts parses Prompt entries from GraphQL response data.
func parsePrompts(data map[string]any) ([]Prompt, error) {
	promptData, ok := data["Prompt"]
	if !ok {
		return nil, nil
	}

	docs, ok := promptData.([]any)
	if !ok {
		return nil, fmt.Errorf("unexpected Prompt type: %T", promptData)
	}

	prompts := make([]Prompt, 0, len(docs))
	for _, d := range docs {
		doc, ok := d.(map[string]any)
		if !ok {
			continue
		}

		p := Prompt{}
		if v, ok := doc["_docID"].(string); ok {
			p.DocID = v
		}
		if v, ok := doc["key"].(string); ok {
			p.Key = v
		}
		if v, ok := doc["text"].(string); ok {
			p.Text = v
		}
		if v, ok := doc["description"].(string); ok {
			p.Description = v
		}
		if v, ok := doc["embedded_hash"].(string); ok {
			p.EmbeddedHash = v
		}
		if vars, ok := doc["variables"].([]any); ok {
			for _, v := range vars {
				if s, ok := v.(string); ok {
					p.Variables = append(p.Variables, s)
				}
			}
		}

		prompts = append(prompts, p)
	}

	return prompts, nil
}

// parseBookOverrides parses BookPromptOverride entries from GraphQL response data.
func parseBookOverrides(data map[string]any) ([]BookPromptOverride, error) {
	overrideData, ok := data["BookPromptOverride"]
	if !ok {
		return nil, nil
	}

	docs, ok := overrideData.([]any)
	if !ok {
		return nil, fmt.Errorf("unexpected BookPromptOverride type: %T", overrideData)
	}

	overrides := make([]BookPromptOverride, 0, len(docs))
	for _, d := range docs {
		doc, ok := d.(map[string]any)
		if !ok {
			continue
		}

		o := BookPromptOverride{}
		if v, ok := doc["_docID"].(string); ok {
			o.DocID = v
		}
		if v, ok := doc["book_id"].(string); ok {
			o.BookID = v
		}
		if v, ok := doc["prompt_key"].(string); ok {
			o.PromptKey = v
		}
		if v, ok := doc["text"].(string); ok {
			o.Text = v
		}
		if v, ok := doc["note"].(string); ok {
			o.Note = v
		}
		if v, ok := doc["created_at"].(string); ok {
			if t, err := time.Parse(time.RFC3339, v); err == nil {
				o.CreatedAt = t
			}
		}
		if v, ok := doc["updated_at"].(string); ok {
			if t, err := time.Parse(time.RFC3339, v); err == nil {
				o.UpdatedAt = t
			}
		}

		overrides = append(overrides, o)
	}

	return overrides, nil
}

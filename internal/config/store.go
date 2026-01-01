package config

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"unicode"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/providers"
)

// ErrAlreadyExists is returned when trying to create a document that already exists.
var ErrAlreadyExists = errors.New("document already exists")

// ErrInvalidKey is returned when a config key contains invalid characters.
var ErrInvalidKey = errors.New("invalid config key")

// ValidateKey checks if a config key contains only allowed characters.
// Valid keys contain: letters, digits, dots, underscores, and hyphens.
// This protects against typos and malformed keys.
func ValidateKey(key string) error {
	if key == "" {
		return fmt.Errorf("%w: key cannot be empty", ErrInvalidKey)
	}
	for i, r := range key {
		if !unicode.IsLetter(r) && !unicode.IsDigit(r) && r != '.' && r != '_' && r != '-' {
			return fmt.Errorf("%w: invalid character %q at position %d", ErrInvalidKey, r, i)
		}
	}
	// Don't allow keys starting or ending with dots
	if key[0] == '.' || key[len(key)-1] == '.' {
		return fmt.Errorf("%w: key cannot start or end with a dot", ErrInvalidKey)
	}
	return nil
}

// Store provides access to configuration stored in DefraDB.
// No caching - reads fresh from DefraDB each time.
type Store interface {
	// Get returns a single config entry by key.
	Get(ctx context.Context, key string) (*Entry, error)

	// Set creates or updates a config entry.
	Set(ctx context.Context, key string, value any, description string) error

	// GetAll returns all config entries.
	GetAll(ctx context.Context) (map[string]Entry, error)

	// GetByPrefix returns config entries matching the prefix.
	GetByPrefix(ctx context.Context, prefix string) (map[string]Entry, error)

	// Delete removes a config entry.
	Delete(ctx context.Context, key string) error
}

// Entry represents a single configuration entry.
type Entry struct {
	Key         string `json:"key"`
	Value       any    `json:"value"`
	Description string `json:"description"`
	DocID       string `json:"_docID,omitempty"` // DefraDB document ID
}

// DefraStore implements Store using DefraDB.
type DefraStore struct {
	client *defra.Client
}

// NewStore creates a new DefraDB-backed config store.
func NewStore(client *defra.Client) *DefraStore {
	return &DefraStore{client: client}
}

// Get returns a single config entry by key.
func (s *DefraStore) Get(ctx context.Context, key string) (*Entry, error) {
	query := fmt.Sprintf(`{
		Config(filter: {name: {_eq: %q}}) {
			_docID
			name
			value
			description
		}
	}`, key)

	resp, err := s.client.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("query failed: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("graphql error: %s", errMsg)
	}

	entries, err := parseConfigEntries(resp.Data)
	if err != nil {
		return nil, err
	}
	if len(entries) == 0 {
		return nil, nil // Not found
	}
	return &entries[0], nil
}

// Set creates or updates a config entry.
func (s *DefraStore) Set(ctx context.Context, key string, value any, description string) error {
	// Check if entry already exists
	existing, err := s.Get(ctx, key)
	if err != nil {
		return fmt.Errorf("failed to check existing: %w", err)
	}

	// Serialize value to JSON for storage
	valueJSON, err := json.Marshal(value)
	if err != nil {
		return fmt.Errorf("failed to marshal value: %w", err)
	}

	input := map[string]any{
		"name":        key,
		"value":       string(valueJSON),
		"description": description,
	}

	if existing != nil {
		// Update existing entry
		err = s.client.Update(ctx, "Config", existing.DocID, input)
		if err != nil {
			return fmt.Errorf("update failed: %w", err)
		}
	} else {
		// Create new entry
		_, err = s.client.Create(ctx, "Config", input)
		if err != nil {
			// If document already exists, that's fine - it's already seeded
			if strings.Contains(err.Error(), "already exists") {
				slog.Debug("config entry already seeded", "key", key)
				return nil
			}
			return fmt.Errorf("create failed: %w", err)
		}
	}
	return nil
}

// GetAll returns all config entries.
func (s *DefraStore) GetAll(ctx context.Context) (map[string]Entry, error) {
	query := `{
		Config {
			_docID
			name
			value
			description
		}
	}`

	resp, err := s.client.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("query failed: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("graphql error: %s", errMsg)
	}

	entries, err := parseConfigEntries(resp.Data)
	if err != nil {
		return nil, err
	}

	result := make(map[string]Entry, len(entries))
	for _, e := range entries {
		result[e.Key] = e
	}
	return result, nil
}

// GetByPrefix returns config entries matching the prefix.
func (s *DefraStore) GetByPrefix(ctx context.Context, prefix string) (map[string]Entry, error) {
	// DefraDB doesn't support LIKE queries, so we filter client-side
	all, err := s.GetAll(ctx)
	if err != nil {
		return nil, err
	}

	result := make(map[string]Entry)
	for key, entry := range all {
		if strings.HasPrefix(key, prefix) {
			result[key] = entry
		}
	}
	return result, nil
}

// Delete removes a config entry by key.
func (s *DefraStore) Delete(ctx context.Context, key string) error {
	existing, err := s.Get(ctx, key)
	if err != nil {
		return fmt.Errorf("failed to find entry: %w", err)
	}
	if existing == nil {
		return nil // Already doesn't exist
	}

	if err := s.client.Delete(ctx, "Config", existing.DocID); err != nil {
		return fmt.Errorf("delete failed: %w", err)
	}
	return nil
}

// parseConfigEntries parses Config entries from GraphQL response data.
func parseConfigEntries(data map[string]any) ([]Entry, error) {
	configData, ok := data["Config"]
	if !ok {
		return nil, nil
	}

	docs, ok := configData.([]any)
	if !ok {
		return nil, fmt.Errorf("unexpected Config type: %T", configData)
	}

	entries := make([]Entry, 0, len(docs))
	for i, d := range docs {
		doc, ok := d.(map[string]any)
		if !ok {
			slog.Warn("skipping malformed config document",
				"index", i,
				"type", fmt.Sprintf("%T", d))
			continue
		}

		entry := Entry{}
		if v, ok := doc["_docID"].(string); ok {
			entry.DocID = v
		}
		if v, ok := doc["name"].(string); ok {
			entry.Key = v
		}
		if v, ok := doc["description"].(string); ok {
			entry.Description = v
		}

		// Value is stored as JSON string, parse it
		if v, ok := doc["value"].(string); ok {
			var parsed any
			if err := json.Unmarshal([]byte(v), &parsed); err != nil {
				// If not valid JSON, use the raw string
				slog.Debug("config value is not valid JSON, using as raw string",
					"key", entry.Key,
					"error", err)
				entry.Value = v
			} else {
				entry.Value = parsed
			}
		} else {
			// Value might already be parsed (DefraDB JSON field)
			entry.Value = doc["value"]
		}

		entries = append(entries, entry)
	}
	return entries, nil
}

// StoreToProviderRegistryConfig builds a ProviderRegistryConfig from the Store.
// It reads all config entries and constructs the provider configuration,
// resolving ${ENV_VAR} references in API keys.
func StoreToProviderRegistryConfig(ctx context.Context, store Store) (providers.RegistryConfig, error) {
	cfg := providers.RegistryConfig{
		OCRProviders: make(map[string]providers.OCRProviderConfig),
		LLMProviders: make(map[string]providers.LLMProviderConfig),
	}

	all, err := store.GetAll(ctx)
	if err != nil {
		return cfg, fmt.Errorf("failed to get config: %w", err)
	}

	// Parse OCR providers: providers.ocr.<name>.<field>
	ocrProviders := extractProviders(all, "providers.ocr.")
	for name, fields := range ocrProviders {
		cfg.OCRProviders[name] = providers.OCRProviderConfig{
			Type:      getString(fields, "type"),
			Model:     getString(fields, "model"),
			APIKey:    ResolveEnvVars(getString(fields, "api_key")),
			RateLimit: getFloat(fields, "rate_limit"),
			Enabled:   getBool(fields, "enabled"),
		}
	}

	// Parse LLM providers: providers.llm.<name>.<field>
	llmProviders := extractProviders(all, "providers.llm.")
	for name, fields := range llmProviders {
		cfg.LLMProviders[name] = providers.LLMProviderConfig{
			Type:      getString(fields, "type"),
			Model:     getString(fields, "model"),
			APIKey:    ResolveEnvVars(getString(fields, "api_key")),
			RateLimit: getFloat(fields, "rate_limit"),
			Enabled:   getBool(fields, "enabled"),
		}
	}

	return cfg, nil
}

// extractProviders groups config entries by provider name.
// For example, "providers.ocr.mistral.type" becomes mistral -> {type: value}
func extractProviders(entries map[string]Entry, prefix string) map[string]map[string]any {
	result := make(map[string]map[string]any)

	for key, entry := range entries {
		if !strings.HasPrefix(key, prefix) {
			continue
		}

		// Remove prefix and split: "mistral.type" -> ["mistral", "type"]
		remainder := strings.TrimPrefix(key, prefix)
		parts := strings.SplitN(remainder, ".", 2)
		if len(parts) != 2 {
			continue
		}

		providerName := parts[0]
		fieldName := parts[1]

		if result[providerName] == nil {
			result[providerName] = make(map[string]any)
		}
		result[providerName][fieldName] = entry.Value
	}

	return result
}

// Helper functions to extract typed values from a map
func getString(m map[string]any, key string) string {
	if v, ok := m[key].(string); ok {
		return v
	}
	return ""
}

func getFloat(m map[string]any, key string) float64 {
	switch v := m[key].(type) {
	case float64:
		return v
	case int:
		return float64(v)
	case int64:
		return float64(v)
	}
	return 0
}

func getBool(m map[string]any, key string) bool {
	if v, ok := m[key].(bool); ok {
		return v
	}
	return false
}

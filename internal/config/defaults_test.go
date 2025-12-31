package config

import (
	"context"
	"errors"
	"testing"
)

func TestDefaultEntries(t *testing.T) {
	entries := DefaultEntries()

	if len(entries) == 0 {
		t.Fatal("DefaultEntries() returned empty slice")
	}

	// Verify required keys exist
	requiredKeys := []string{
		"providers.ocr.mistral.type",
		"providers.ocr.mistral.api_key",
		"providers.ocr.mistral.rate_limit",
		"providers.ocr.mistral.enabled",
		"providers.ocr.paddle.type",
		"providers.llm.openrouter.type",
		"defaults.ocr_providers",
		"defaults.llm_provider",
		"defaults.max_workers",
	}

	keys := make(map[string]bool)
	for _, e := range entries {
		keys[e.Key] = true
	}

	for _, key := range requiredKeys {
		if !keys[key] {
			t.Errorf("DefaultEntries() missing required key: %s", key)
		}
	}
}

func TestGetDefault(t *testing.T) {
	t.Run("existing_key", func(t *testing.T) {
		entry := GetDefault("providers.ocr.mistral.type")
		if entry == nil {
			t.Fatal("GetDefault() returned nil for existing key")
		}
		if entry.Value != "mistral-ocr" {
			t.Errorf("GetDefault() Value = %v, want %q", entry.Value, "mistral-ocr")
		}
	})

	t.Run("non_existent_key", func(t *testing.T) {
		entry := GetDefault("does.not.exist")
		if entry != nil {
			t.Errorf("GetDefault() = %v, want nil for non-existent key", entry)
		}
	})
}

// mockStore implements Store interface for testing.
type mockStore struct {
	data map[string]Entry
}

func newMockStore() *mockStore {
	return &mockStore{data: make(map[string]Entry)}
}

func (m *mockStore) Get(_ context.Context, key string) (*Entry, error) {
	if e, ok := m.data[key]; ok {
		return &e, nil
	}
	return nil, nil
}

func (m *mockStore) Set(_ context.Context, key string, value any, description string) error {
	m.data[key] = Entry{Key: key, Value: value, Description: description}
	return nil
}

func (m *mockStore) GetAll(_ context.Context) (map[string]Entry, error) {
	return m.data, nil
}

func (m *mockStore) GetByPrefix(_ context.Context, prefix string) (map[string]Entry, error) {
	result := make(map[string]Entry)
	for k, v := range m.data {
		if len(k) >= len(prefix) && k[:len(prefix)] == prefix {
			result[k] = v
		}
	}
	return result, nil
}

func (m *mockStore) Delete(_ context.Context, key string) error {
	delete(m.data, key)
	return nil
}

func TestSeedDefaults(t *testing.T) {
	t.Run("seeds_all_defaults", func(t *testing.T) {
		store := newMockStore()
		ctx := context.Background()

		err := SeedDefaults(ctx, store, nil)
		if err != nil {
			t.Fatalf("SeedDefaults() error = %v", err)
		}

		defaults := DefaultEntries()
		if len(store.data) != len(defaults) {
			t.Errorf("SeedDefaults() seeded %d entries, want %d", len(store.data), len(defaults))
		}
	})

	t.Run("idempotent", func(t *testing.T) {
		store := newMockStore()
		ctx := context.Background()

		// Seed once
		err := SeedDefaults(ctx, store, nil)
		if err != nil {
			t.Fatalf("SeedDefaults() first call error = %v", err)
		}
		firstCount := len(store.data)

		// Modify a value
		store.data["providers.ocr.mistral.type"] = Entry{
			Key:   "providers.ocr.mistral.type",
			Value: "custom-type",
		}

		// Seed again
		err = SeedDefaults(ctx, store, nil)
		if err != nil {
			t.Fatalf("SeedDefaults() second call error = %v", err)
		}

		// Count should be the same
		if len(store.data) != firstCount {
			t.Errorf("SeedDefaults() changed entry count from %d to %d", firstCount, len(store.data))
		}

		// Custom value should be preserved
		entry, _ := store.Get(ctx, "providers.ocr.mistral.type")
		if entry.Value != "custom-type" {
			t.Error("SeedDefaults() overwrote existing value")
		}
	})
}

func TestResetToDefault(t *testing.T) {
	t.Run("resets_to_default", func(t *testing.T) {
		store := newMockStore()
		ctx := context.Background()

		// Set a custom value
		store.Set(ctx, "providers.ocr.mistral.type", "custom-value", "")

		// Reset to default
		err := ResetToDefault(ctx, store, "providers.ocr.mistral.type")
		if err != nil {
			t.Fatalf("ResetToDefault() error = %v", err)
		}

		entry, _ := store.Get(ctx, "providers.ocr.mistral.type")
		if entry.Value != "mistral-ocr" {
			t.Errorf("ResetToDefault() Value = %v, want %q", entry.Value, "mistral-ocr")
		}
	})

	t.Run("error_for_unknown_key", func(t *testing.T) {
		store := newMockStore()
		ctx := context.Background()

		err := ResetToDefault(ctx, store, "does.not.exist")
		if err == nil {
			t.Error("ResetToDefault() should error for unknown key")
		}
		if !errors.Is(err, ErrNoDefault) {
			t.Errorf("ResetToDefault() error should wrap ErrNoDefault, got %v", err)
		}
	})
}

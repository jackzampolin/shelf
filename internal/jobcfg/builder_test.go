package jobcfg

import (
	"context"
	"testing"

	"github.com/jackzampolin/shelf/internal/config"
)

// mockStore implements config.Store for testing.
type mockStore struct {
	data map[string]config.Entry
}

func newMockStore() *mockStore {
	return &mockStore{data: make(map[string]config.Entry)}
}

func (m *mockStore) Get(_ context.Context, key string) (*config.Entry, error) {
	if e, ok := m.data[key]; ok {
		return &e, nil
	}
	return nil, nil
}

func (m *mockStore) Set(_ context.Context, key string, value any, description string) error {
	m.data[key] = config.Entry{Key: key, Value: value, Description: description}
	return nil
}

func (m *mockStore) GetAll(_ context.Context) (map[string]config.Entry, error) {
	return m.data, nil
}

func (m *mockStore) GetByPrefix(_ context.Context, prefix string) (map[string]config.Entry, error) {
	result := make(map[string]config.Entry)
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

func TestBuilder_getString(t *testing.T) {
	ctx := context.Background()

	t.Run("reads_from_store", func(t *testing.T) {
		store := newMockStore()
		store.Set(ctx, "defaults.llm_provider", "custom-provider", "")

		b := NewBuilder(store)
		val, err := b.getString(ctx, "defaults.llm_provider")
		if err != nil {
			t.Fatalf("getString() error = %v", err)
		}
		if val != "custom-provider" {
			t.Errorf("getString() = %q, want %q", val, "custom-provider")
		}
	})

	t.Run("falls_back_to_default", func(t *testing.T) {
		store := newMockStore()
		// Don't set anything - should fall back to default

		b := NewBuilder(store)
		val, err := b.getString(ctx, "defaults.llm_provider")
		if err != nil {
			t.Fatalf("getString() error = %v", err)
		}
		// Should get the default value from config.GetDefault
		def := config.GetDefault("defaults.llm_provider")
		if def == nil {
			t.Fatal("expected default to exist for defaults.llm_provider")
		}
		if val != def.Value.(string) {
			t.Errorf("getString() = %q, want default %q", val, def.Value)
		}
	})

	t.Run("error_for_wrong_type", func(t *testing.T) {
		store := newMockStore()
		store.Set(ctx, "defaults.llm_provider", 123, "") // int instead of string

		b := NewBuilder(store)
		_, err := b.getString(ctx, "defaults.llm_provider")
		if err == nil {
			t.Error("getString() should error for wrong type")
		}
	})

	t.Run("error_for_unknown_key_without_default", func(t *testing.T) {
		store := newMockStore()

		b := NewBuilder(store)
		_, err := b.getString(ctx, "does.not.exist")
		if err == nil {
			t.Error("getString() should error for unknown key without default")
		}
	})
}

func TestBuilder_getBool(t *testing.T) {
	ctx := context.Background()

	t.Run("reads_from_store", func(t *testing.T) {
		store := newMockStore()
		store.Set(ctx, "defaults.debug_agents", true, "")

		b := NewBuilder(store)
		val, err := b.getBool(ctx, "defaults.debug_agents")
		if err != nil {
			t.Fatalf("getBool() error = %v", err)
		}
		if val != true {
			t.Errorf("getBool() = %v, want true", val)
		}
	})

	t.Run("falls_back_to_default", func(t *testing.T) {
		store := newMockStore()

		b := NewBuilder(store)
		val, err := b.getBool(ctx, "defaults.debug_agents")
		if err != nil {
			t.Fatalf("getBool() error = %v", err)
		}
		// Default is false
		if val != false {
			t.Errorf("getBool() = %v, want false (default)", val)
		}
	})

	t.Run("error_for_wrong_type", func(t *testing.T) {
		store := newMockStore()
		store.Set(ctx, "defaults.debug_agents", "true", "") // string instead of bool

		b := NewBuilder(store)
		_, err := b.getBool(ctx, "defaults.debug_agents")
		if err == nil {
			t.Error("getBool() should error for wrong type")
		}
	})
}

func TestBuilder_getStringSlice(t *testing.T) {
	ctx := context.Background()

	t.Run("reads_string_slice_from_store", func(t *testing.T) {
		store := newMockStore()
		store.Set(ctx, "defaults.ocr_providers", []string{"provider1", "provider2"}, "")

		b := NewBuilder(store)
		val, err := b.getStringSlice(ctx, "defaults.ocr_providers")
		if err != nil {
			t.Fatalf("getStringSlice() error = %v", err)
		}
		if len(val) != 2 || val[0] != "provider1" || val[1] != "provider2" {
			t.Errorf("getStringSlice() = %v, want [provider1 provider2]", val)
		}
	})

	t.Run("handles_any_slice_from_json", func(t *testing.T) {
		store := newMockStore()
		// JSON unmarshaling produces []any, not []string
		store.Set(ctx, "defaults.ocr_providers", []any{"provider1", "provider2"}, "")

		b := NewBuilder(store)
		val, err := b.getStringSlice(ctx, "defaults.ocr_providers")
		if err != nil {
			t.Fatalf("getStringSlice() error = %v", err)
		}
		if len(val) != 2 || val[0] != "provider1" || val[1] != "provider2" {
			t.Errorf("getStringSlice() = %v, want [provider1 provider2]", val)
		}
	})

	t.Run("error_for_non_string_item", func(t *testing.T) {
		store := newMockStore()
		store.Set(ctx, "defaults.ocr_providers", []any{"provider1", 123}, "")

		b := NewBuilder(store)
		_, err := b.getStringSlice(ctx, "defaults.ocr_providers")
		if err == nil {
			t.Error("getStringSlice() should error for non-string item in slice")
		}
	})

	t.Run("falls_back_to_default", func(t *testing.T) {
		store := newMockStore()

		b := NewBuilder(store)
		val, err := b.getStringSlice(ctx, "defaults.ocr_providers")
		if err != nil {
			t.Fatalf("getStringSlice() error = %v", err)
		}
		// Default should be ["mistral", "paddle"]
		if len(val) != 2 || val[0] != "mistral" || val[1] != "paddle" {
			t.Errorf("getStringSlice() = %v, want [mistral paddle]", val)
		}
	})
}

func TestBuilder_GetInt(t *testing.T) {
	ctx := context.Background()

	t.Run("reads_int_from_store", func(t *testing.T) {
		store := newMockStore()
		store.Set(ctx, "providers.ocr.mistral.timeout_seconds", 100, "")

		b := NewBuilder(store)
		val, err := b.GetInt(ctx, "providers.ocr.mistral.timeout_seconds")
		if err != nil {
			t.Fatalf("GetInt() error = %v", err)
		}
		if val != 100 {
			t.Errorf("GetInt() = %d, want 100", val)
		}
	})

	t.Run("handles_float64_from_json", func(t *testing.T) {
		store := newMockStore()
		// JSON unmarshaling produces float64 for numbers
		store.Set(ctx, "providers.ocr.mistral.timeout_seconds", float64(100), "")

		b := NewBuilder(store)
		val, err := b.GetInt(ctx, "providers.ocr.mistral.timeout_seconds")
		if err != nil {
			t.Fatalf("GetInt() error = %v", err)
		}
		if val != 100 {
			t.Errorf("GetInt() = %d, want 100", val)
		}
	})

	t.Run("falls_back_to_default", func(t *testing.T) {
		store := newMockStore()

		b := NewBuilder(store)
		val, err := b.GetInt(ctx, "providers.ocr.mistral.timeout_seconds")
		if err != nil {
			t.Fatalf("GetInt() error = %v", err)
		}
		// Default is 500
		if val != 500 {
			t.Errorf("GetInt() = %d, want 500 (default)", val)
		}
	})

	t.Run("error_for_wrong_type", func(t *testing.T) {
		store := newMockStore()
		store.Set(ctx, "providers.ocr.mistral.timeout_seconds", "100", "")

		b := NewBuilder(store)
		_, err := b.GetInt(ctx, "providers.ocr.mistral.timeout_seconds")
		if err == nil {
			t.Error("GetInt() should error for wrong type")
		}
	})
}

func TestBuilder_ProcessBookConfig(t *testing.T) {
	ctx := context.Background()

	t.Run("builds_config_from_store", func(t *testing.T) {
		store := newMockStore()
		store.Set(ctx, "defaults.ocr_providers", []string{"custom1", "custom2"}, "")
		store.Set(ctx, "defaults.llm_provider", "custom-llm", "")
		store.Set(ctx, "defaults.debug_agents", true, "")

		b := NewBuilder(store)
		cfg, err := b.ProcessBookConfig(ctx)
		if err != nil {
			t.Fatalf("ProcessBookConfig() error = %v", err)
		}

		if len(cfg.OcrProviders) != 2 || cfg.OcrProviders[0] != "custom1" {
			t.Errorf("OcrProviders = %v, want [custom1 custom2]", cfg.OcrProviders)
		}
		if cfg.BlendProvider != "custom-llm" {
			t.Errorf("BlendProvider = %q, want %q", cfg.BlendProvider, "custom-llm")
		}
		if cfg.LabelProvider != "custom-llm" {
			t.Errorf("LabelProvider = %q, want %q", cfg.LabelProvider, "custom-llm")
		}
		if cfg.MetadataProvider != "custom-llm" {
			t.Errorf("MetadataProvider = %q, want %q", cfg.MetadataProvider, "custom-llm")
		}
		if cfg.TocProvider != "custom-llm" {
			t.Errorf("TocProvider = %q, want %q", cfg.TocProvider, "custom-llm")
		}
		if cfg.DebugAgents != true {
			t.Errorf("DebugAgents = %v, want true", cfg.DebugAgents)
		}
	})

	t.Run("uses_defaults_when_store_empty", func(t *testing.T) {
		store := newMockStore()

		b := NewBuilder(store)
		cfg, err := b.ProcessBookConfig(ctx)
		if err != nil {
			t.Fatalf("ProcessBookConfig() error = %v", err)
		}

		// Should use defaults
		if len(cfg.OcrProviders) != 2 || cfg.OcrProviders[0] != "mistral" {
			t.Errorf("OcrProviders = %v, want [mistral paddle]", cfg.OcrProviders)
		}
		if cfg.BlendProvider != "openrouter" {
			t.Errorf("BlendProvider = %q, want %q", cfg.BlendProvider, "openrouter")
		}
		if cfg.DebugAgents != false {
			t.Errorf("DebugAgents = %v, want false", cfg.DebugAgents)
		}
	})
}

func TestBuilder_LinkTocConfig(t *testing.T) {
	ctx := context.Background()

	t.Run("force_flag_defaults_to_false", func(t *testing.T) {
		store := newMockStore()

		b := NewBuilder(store)
		cfg, err := b.LinkTocConfig(ctx)
		if err != nil {
			t.Fatalf("LinkTocConfig() error = %v", err)
		}

		if cfg.Force != false {
			t.Errorf("Force = %v, want false (caller should set if needed)", cfg.Force)
		}
	})
}

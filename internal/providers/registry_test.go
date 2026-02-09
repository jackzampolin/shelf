package providers

import (
	"sync"
	"testing"
)

func TestRegistry(t *testing.T) {
	t.Run("register and get LLM", func(t *testing.T) {
		r := NewRegistry()
		mock := NewMockClient()

		r.RegisterLLM("test-llm", mock)

		client, err := r.GetLLM("test-llm")
		if err != nil {
			t.Fatalf("GetLLM() error = %v", err)
		}
		if client != mock {
			t.Error("got different client than registered")
		}
	})

	t.Run("register and get OCR", func(t *testing.T) {
		r := NewRegistry()
		mock := NewMockOCRProvider()

		r.RegisterOCR("test-ocr", mock)

		provider, err := r.GetOCR("test-ocr")
		if err != nil {
			t.Fatalf("GetOCR() error = %v", err)
		}
		if provider != mock {
			t.Error("got different provider than registered")
		}
	})

	t.Run("get nonexistent LLM", func(t *testing.T) {
		r := NewRegistry()

		_, err := r.GetLLM("nonexistent")
		if err == nil {
			t.Error("expected error for nonexistent LLM")
		}
	})

	t.Run("get nonexistent OCR", func(t *testing.T) {
		r := NewRegistry()

		_, err := r.GetOCR("nonexistent")
		if err == nil {
			t.Error("expected error for nonexistent OCR")
		}
	})

	t.Run("list providers", func(t *testing.T) {
		r := NewRegistry()
		r.RegisterLLM("llm1", NewMockClient())
		r.RegisterLLM("llm2", NewMockClient())
		r.RegisterOCR("ocr1", NewMockOCRProvider())

		llmList := r.ListLLM()
		if len(llmList) != 2 {
			t.Errorf("ListLLM() returned %d items, want 2", len(llmList))
		}

		ocrList := r.ListOCR()
		if len(ocrList) != 1 {
			t.Errorf("ListOCR() returned %d items, want 1", len(ocrList))
		}
	})

	t.Run("has providers", func(t *testing.T) {
		r := NewRegistry()
		r.RegisterLLM("my-llm", NewMockClient())
		r.RegisterOCR("my-ocr", NewMockOCRProvider())

		if !r.HasLLM("my-llm") {
			t.Error("HasLLM() = false for registered LLM")
		}
		if r.HasLLM("other-llm") {
			t.Error("HasLLM() = true for unregistered LLM")
		}
		if !r.HasOCR("my-ocr") {
			t.Error("HasOCR() = false for registered OCR")
		}
		if r.HasOCR("other-ocr") {
			t.Error("HasOCR() = true for unregistered OCR")
		}
	})

	t.Run("concurrent access", func(t *testing.T) {
		r := NewRegistry()

		var wg sync.WaitGroup
		for i := 0; i < 10; i++ {
			wg.Add(2)
			go func(n int) {
				defer wg.Done()
				r.RegisterLLM("concurrent-llm", NewMockClient())
			}(i)
			go func(n int) {
				defer wg.Done()
				r.GetLLM("concurrent-llm") // May fail, that's ok
			}(i)
		}
		wg.Wait()
	})
}

func TestNewRegistryFromConfig(t *testing.T) {
	t.Run("registers providers from config", func(t *testing.T) {
		r := NewRegistryFromConfig(RegistryConfig{
			LLMProviders: map[string]LLMProviderConfig{
				"openrouter": {
					Type:    "openrouter",
					Model:   "anthropic/claude-sonnet-4",
					APIKey:  "test-openrouter-key",
					Enabled: true,
				},
			},
			OCRProviders: map[string]OCRProviderConfig{
				"mistral": {
					Type:    "mistral-ocr",
					APIKey:  "test-mistral-key",
					Enabled: true,
				},
			},
			TTSProviders: map[string]TTSProviderConfig{
				"openai": {
					Type:    "openai",
					Model:   "tts-1-hd",
					Voice:   "onyx",
					APIKey:  "test-openai-key",
					Enabled: true,
				},
			},
		})

		if !r.HasLLM("openrouter") {
			t.Error("expected openrouter to be registered")
		}
		if !r.HasOCR("mistral") {
			t.Error("expected mistral to be registered")
		}
		if !r.HasTTS("openai") {
			t.Error("expected openai TTS provider to be registered")
		}
	})

	t.Run("skips disabled providers", func(t *testing.T) {
		r := NewRegistryFromConfig(RegistryConfig{
			LLMProviders: map[string]LLMProviderConfig{
				"openrouter": {
					Type:    "openrouter",
					APIKey:  "test-key",
					Enabled: false, // Disabled
				},
			},
			OCRProviders: map[string]OCRProviderConfig{
				"mistral": {
					Type:    "mistral-ocr",
					APIKey:  "test-key",
					Enabled: false, // Disabled
				},
			},
		})

		if r.HasLLM("openrouter") {
			t.Error("disabled provider should not be registered")
		}
		if r.HasOCR("mistral") {
			t.Error("disabled provider should not be registered")
		}
	})

	t.Run("skips providers without API keys", func(t *testing.T) {
		r := NewRegistryFromConfig(RegistryConfig{
			LLMProviders: map[string]LLMProviderConfig{
				"openrouter": {
					Type:    "openrouter",
					APIKey:  "", // Empty
					Enabled: true,
				},
			},
			OCRProviders: map[string]OCRProviderConfig{
				"mistral": {
					Type:    "mistral-ocr",
					APIKey:  "", // Empty
					Enabled: true,
				},
			},
		})

		if r.HasLLM("openrouter") {
			t.Error("provider without API key should not be registered")
		}
		if r.HasOCR("mistral") {
			t.Error("provider without API key should not be registered")
		}
	})

	t.Run("uses custom model for LLM provider", func(t *testing.T) {
		r := NewRegistryFromConfig(RegistryConfig{
			LLMProviders: map[string]LLMProviderConfig{
				"openrouter": {
					Type:    "openrouter",
					Model:   "custom-model",
					APIKey:  "test-key",
					Enabled: true,
				},
			},
		})

		client, _ := r.GetLLM("openrouter")
		orClient, ok := client.(*OpenRouterClient)
		if !ok {
			t.Fatal("expected OpenRouterClient")
		}
		if orClient.defaultModel != "custom-model" {
			t.Errorf("expected custom-model, got %s", orClient.defaultModel)
		}
	})
}

func TestRegistry_Reload(t *testing.T) {
	t.Run("adds new providers on reload", func(t *testing.T) {
		r := NewRegistryFromConfig(RegistryConfig{}) // Start empty

		if r.HasLLM("openrouter") {
			t.Error("should start without openrouter")
		}

		// Reload with new config
		r.Reload(RegistryConfig{
			LLMProviders: map[string]LLMProviderConfig{
				"openrouter": {
					Type:    "openrouter",
					APIKey:  "new-key",
					Enabled: true,
				},
			},
		})

		if !r.HasLLM("openrouter") {
			t.Error("expected openrouter after reload")
		}
	})

	t.Run("removes providers on reload", func(t *testing.T) {
		r := NewRegistryFromConfig(RegistryConfig{
			LLMProviders: map[string]LLMProviderConfig{
				"openrouter": {
					Type:    "openrouter",
					APIKey:  "key",
					Enabled: true,
				},
			},
			OCRProviders: map[string]OCRProviderConfig{
				"mistral": {
					Type:    "mistral-ocr",
					APIKey:  "key",
					Enabled: true,
				},
			},
		})

		if !r.HasLLM("openrouter") || !r.HasOCR("mistral") {
			t.Error("should start with both providers")
		}

		// Reload with empty config
		r.Reload(RegistryConfig{})

		if r.HasLLM("openrouter") {
			t.Error("openrouter should be removed after reload")
		}
		if r.HasOCR("mistral") {
			t.Error("mistral should be removed after reload")
		}
	})

	t.Run("updates providers with changed API keys", func(t *testing.T) {
		r := NewRegistryFromConfig(RegistryConfig{
			LLMProviders: map[string]LLMProviderConfig{
				"openrouter": {
					Type:    "openrouter",
					APIKey:  "old-key",
					Enabled: true,
				},
			},
		})

		client, _ := r.GetLLM("openrouter")
		oldClient := client.(*OpenRouterClient)
		if oldClient.apiKey != "old-key" {
			t.Error("should start with old key")
		}

		// Reload with new key
		r.Reload(RegistryConfig{
			LLMProviders: map[string]LLMProviderConfig{
				"openrouter": {
					Type:    "openrouter",
					APIKey:  "new-key",
					Enabled: true,
				},
			},
		})

		client, _ = r.GetLLM("openrouter")
		newClient := client.(*OpenRouterClient)
		if newClient.apiKey != "new-key" {
			t.Errorf("expected new-key, got %s", newClient.apiKey)
		}
	})

	t.Run("keeps providers with unchanged config", func(t *testing.T) {
		r := NewRegistryFromConfig(RegistryConfig{
			LLMProviders: map[string]LLMProviderConfig{
				"openrouter": {
					Type:      "openrouter",
					Model:     "test-model",
					APIKey:    "same-key",
					RateLimit: 60, // Explicit rate limit
					Enabled:   true,
				},
			},
		})

		client1, _ := r.GetLLM("openrouter")

		// Reload with same config (including same rate limit)
		r.Reload(RegistryConfig{
			LLMProviders: map[string]LLMProviderConfig{
				"openrouter": {
					Type:      "openrouter",
					Model:     "test-model",
					APIKey:    "same-key",
					RateLimit: 60, // Same rate limit
					Enabled:   true,
				},
			},
		})

		client2, _ := r.GetLLM("openrouter")

		// Should be the same instance
		if client1 != client2 {
			t.Error("client should not be replaced when config unchanged")
		}
	})

	t.Run("concurrent reload is safe", func(t *testing.T) {
		r := NewRegistryFromConfig(RegistryConfig{
			LLMProviders: map[string]LLMProviderConfig{
				"openrouter": {
					Type:    "openrouter",
					APIKey:  "key",
					Enabled: true,
				},
			},
		})

		var wg sync.WaitGroup
		for i := 0; i < 10; i++ {
			wg.Add(2)
			go func(n int) {
				defer wg.Done()
				r.Reload(RegistryConfig{
					LLMProviders: map[string]LLMProviderConfig{
						"openrouter": {
							Type:    "openrouter",
							APIKey:  "key-" + string(rune('a'+n)),
							Enabled: true,
						},
					},
				})
			}(i)
			go func() {
				defer wg.Done()
				r.GetLLM("openrouter") // May fail, that's ok
			}()
		}
		wg.Wait()
	})
}

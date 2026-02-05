// Package jobcfg provides builders to construct job configurations from the DefraDB config store.
// This package bridges the config store and job packages, reading settings at job creation time
// so that UI changes are immediately reflected. When a config key is not found in DefraDB,
// it falls back to the compiled-in defaults from config.DefaultEntries().
package jobcfg

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/jackzampolin/shelf/internal/config"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/jobs/process_book"
	"github.com/jackzampolin/shelf/internal/jobs/tts_generate"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// Builder reads job configurations from the DefraDB config store.
// This is the primary way to get job configs at runtime, ensuring UI changes
// are reflected immediately when jobs are created.
type Builder struct {
	store config.Store
}

func loggerFromContext(ctx context.Context) *slog.Logger {
	if logger := svcctx.LoggerFrom(ctx); logger != nil {
		return logger
	}
	return slog.Default()
}

// NewBuilder creates a new builder that reads from the given store.
func NewBuilder(store config.Store) *Builder {
	return &Builder{store: store}
}

// ProcessBookConfig builds a process_book.Config from the store.
// The returned config has standard variant applied by default (all stages enabled).
func (b *Builder) ProcessBookConfig(ctx context.Context) (process_book.Config, error) {
	ocrProviders, err := b.getStringSlice(ctx, "defaults.ocr_providers")
	if err != nil {
		return process_book.Config{}, fmt.Errorf("failed to get ocr_providers: %w", err)
	}

	llmProvider, err := b.getString(ctx, "defaults.llm_provider")
	if err != nil {
		return process_book.Config{}, fmt.Errorf("failed to get llm_provider: %w", err)
	}

	debugAgents, err := b.getBool(ctx, "defaults.debug_agents")
	if err != nil {
		return process_book.Config{}, fmt.Errorf("failed to get debug_agents: %w", err)
	}

	cfg := process_book.Config{
		OcrProviders:     ocrProviders,
		MetadataProvider: llmProvider,
		TocProvider:      llmProvider,
		DebugAgents:      debugAgents,
	}

	// Apply standard variant by default (enables all stages)
	cfg.ApplyVariant(process_book.VariantStandard)

	return cfg, nil
}

// Helper methods to get typed values from the store

func (b *Builder) getString(ctx context.Context, key string) (string, error) {
	entry, err := b.store.Get(ctx, key)
	if err != nil {
		return "", err
	}
	if entry == nil {
		// Fall back to default
		def := config.GetDefault(key)
		if def == nil {
			return "", fmt.Errorf("no value or default for key %q", key)
		}
		if s, ok := def.Value.(string); ok {
			loggerFromContext(ctx).Debug("config key not in DB, using default",
				"key", key, "default", s)
			return s, nil
		}
		return "", fmt.Errorf("default for %q is not a string (got %T: %v)", key, def.Value, def.Value)
	}
	if s, ok := entry.Value.(string); ok {
		return s, nil
	}
	return "", fmt.Errorf("value for %q is not a string (got %T: %v)", key, entry.Value, entry.Value)
}

func (b *Builder) getBool(ctx context.Context, key string) (bool, error) {
	entry, err := b.store.Get(ctx, key)
	if err != nil {
		return false, err
	}
	if entry == nil {
		// Fall back to default
		def := config.GetDefault(key)
		if def == nil {
			return false, fmt.Errorf("no value or default for key %q", key)
		}
		if v, ok := def.Value.(bool); ok {
			loggerFromContext(ctx).Debug("config key not in DB, using default",
				"key", key, "default", v)
			return v, nil
		}
		return false, fmt.Errorf("default for %q is not a bool (got %T: %v)", key, def.Value, def.Value)
	}
	if v, ok := entry.Value.(bool); ok {
		return v, nil
	}
	return false, fmt.Errorf("value for %q is not a bool (got %T: %v)", key, entry.Value, entry.Value)
}

func (b *Builder) getStringSlice(ctx context.Context, key string) ([]string, error) {
	entry, err := b.store.Get(ctx, key)
	if err != nil {
		return nil, err
	}
	if entry == nil {
		// Fall back to default
		def := config.GetDefault(key)
		if def == nil {
			return nil, fmt.Errorf("no value or default for key %q", key)
		}
		if s, ok := def.Value.([]string); ok {
			loggerFromContext(ctx).Debug("config key not in DB, using default",
				"key", key, "default", s)
			return s, nil
		}
		return nil, fmt.Errorf("default for %q is not a string slice (got %T: %v)", key, def.Value, def.Value)
	}

	// Handle both []string and []any (from JSON unmarshaling)
	switch v := entry.Value.(type) {
	case []string:
		return v, nil
	case []any:
		result := make([]string, 0, len(v))
		for _, item := range v {
			if s, ok := item.(string); ok {
				result = append(result, s)
			} else {
				return nil, fmt.Errorf("value for %q contains non-string item (got %T: %v)", key, item, item)
			}
		}
		return result, nil
	default:
		return nil, fmt.Errorf("value for %q is not a string slice (got %T: %v)", key, entry.Value, entry.Value)
	}
}

// GetInt reads an integer config value from the store.
// Exported for use by other packages that need stage-specific settings.
func (b *Builder) GetInt(ctx context.Context, key string) (int, error) {
	entry, err := b.store.Get(ctx, key)
	if err != nil {
		return 0, err
	}
	if entry == nil {
		// Fall back to default
		def := config.GetDefault(key)
		if def == nil {
			return 0, fmt.Errorf("no value or default for key %q", key)
		}
		v, err := toInt(def.Value, key)
		if err != nil {
			return 0, err
		}
		loggerFromContext(ctx).Debug("config key not in DB, using default",
			"key", key, "default", v)
		return v, nil
	}
	return toInt(entry.Value, key)
}

func toInt(v any, key string) (int, error) {
	switch val := v.(type) {
	case int:
		return val, nil
	case int64:
		return int(val), nil
	case float64:
		return int(val), nil
	default:
		return 0, fmt.Errorf("value for %q is not an int (got %T: %v)", key, v, v)
	}
}

// JobFactory functions that read config from DefraDB at job creation time.
// These are used during job resumption to ensure resumed jobs use current config.

// ProcessBookJobFactory returns a JobFactory that reads config from the store.
func ProcessBookJobFactory(store config.Store) jobs.JobFactory {
	return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
		builder := NewBuilder(store)
		cfg, err := builder.ProcessBookConfig(ctx)
		if err != nil {
			return nil, fmt.Errorf("failed to build config: %w", err)
		}
		return process_book.NewJob(ctx, cfg, bookID)
	})
}

// TTSConfig builds a tts_generate.Config from the store.
func (b *Builder) TTSConfig(ctx context.Context) (tts_generate.Config, error) {
	ttsProvider, err := b.getString(ctx, "defaults.tts_provider")
	if err != nil {
		return tts_generate.Config{}, fmt.Errorf("failed to get tts_provider: %w", err)
	}

	// Voice and format are optional and can be overridden per request.
	// Keep format empty here so resume can preserve the existing BookAudio format.
	return tts_generate.Config{
		TTSProvider: ttsProvider,
		Format:      "",
	}, nil
}

// TTSJobFactory returns a JobFactory that reads config from the store.
func TTSJobFactory(store config.Store) jobs.JobFactory {
	return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
		builder := NewBuilder(store)
		cfg, err := builder.TTSConfig(ctx)
		if err != nil {
			return nil, fmt.Errorf("failed to build TTS config: %w", err)
		}
		return tts_generate.NewJob(ctx, cfg, bookID)
	})
}

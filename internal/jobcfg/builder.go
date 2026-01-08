// Package jobcfg provides builders to construct job configurations from the DefraDB config store.
// This package bridges the config store and job packages, reading settings at job creation time
// so that UI changes are immediately reflected.
package jobcfg

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/config"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/jobs/common_structure"
	"github.com/jackzampolin/shelf/internal/jobs/finalize_toc"
	"github.com/jackzampolin/shelf/internal/jobs/label_book"
	"github.com/jackzampolin/shelf/internal/jobs/link_toc"
	"github.com/jackzampolin/shelf/internal/jobs/metadata_book"
	"github.com/jackzampolin/shelf/internal/jobs/ocr_book"
	"github.com/jackzampolin/shelf/internal/jobs/process_book"
	"github.com/jackzampolin/shelf/internal/jobs/toc_book"
)

// Builder reads job configurations from the DefraDB config store.
// This is the primary way to get job configs at runtime, ensuring UI changes
// are reflected immediately when jobs are created.
type Builder struct {
	store config.Store
}

// NewBuilder creates a new builder that reads from the given store.
func NewBuilder(store config.Store) *Builder {
	return &Builder{store: store}
}

// ProcessBookConfig builds a process_book.Config from the store.
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

	return process_book.Config{
		OcrProviders:     ocrProviders,
		BlendProvider:    llmProvider,
		LabelProvider:    llmProvider,
		MetadataProvider: llmProvider,
		TocProvider:      llmProvider,
		DebugAgents:      debugAgents,
	}, nil
}

// OcrBookConfig builds an ocr_book.Config from the store.
func (b *Builder) OcrBookConfig(ctx context.Context) (ocr_book.Config, error) {
	ocrProviders, err := b.getStringSlice(ctx, "defaults.ocr_providers")
	if err != nil {
		return ocr_book.Config{}, fmt.Errorf("failed to get ocr_providers: %w", err)
	}

	llmProvider, err := b.getString(ctx, "defaults.llm_provider")
	if err != nil {
		return ocr_book.Config{}, fmt.Errorf("failed to get llm_provider: %w", err)
	}

	return ocr_book.Config{
		OcrProviders:  ocrProviders,
		BlendProvider: llmProvider,
	}, nil
}

// LabelBookConfig builds a label_book.Config from the store.
func (b *Builder) LabelBookConfig(ctx context.Context) (label_book.Config, error) {
	llmProvider, err := b.getString(ctx, "defaults.llm_provider")
	if err != nil {
		return label_book.Config{}, fmt.Errorf("failed to get llm_provider: %w", err)
	}

	return label_book.Config{
		LabelProvider: llmProvider,
	}, nil
}

// MetadataBookConfig builds a metadata_book.Config from the store.
func (b *Builder) MetadataBookConfig(ctx context.Context) (metadata_book.Config, error) {
	llmProvider, err := b.getString(ctx, "defaults.llm_provider")
	if err != nil {
		return metadata_book.Config{}, fmt.Errorf("failed to get llm_provider: %w", err)
	}

	return metadata_book.Config{
		MetadataProvider: llmProvider,
	}, nil
}

// TocBookConfig builds a toc_book.Config from the store.
func (b *Builder) TocBookConfig(ctx context.Context) (toc_book.Config, error) {
	llmProvider, err := b.getString(ctx, "defaults.llm_provider")
	if err != nil {
		return toc_book.Config{}, fmt.Errorf("failed to get llm_provider: %w", err)
	}

	debugAgents, err := b.getBool(ctx, "defaults.debug_agents")
	if err != nil {
		return toc_book.Config{}, fmt.Errorf("failed to get debug_agents: %w", err)
	}

	return toc_book.Config{
		TocProvider: llmProvider,
		DebugAgents: debugAgents,
	}, nil
}

// LinkTocConfig builds a link_toc.Config from the store.
// Note: Force flag is not stored - it's passed per-request.
func (b *Builder) LinkTocConfig(ctx context.Context) (link_toc.Config, error) {
	llmProvider, err := b.getString(ctx, "defaults.llm_provider")
	if err != nil {
		return link_toc.Config{}, fmt.Errorf("failed to get llm_provider: %w", err)
	}

	debugAgents, err := b.getBool(ctx, "defaults.debug_agents")
	if err != nil {
		return link_toc.Config{}, fmt.Errorf("failed to get debug_agents: %w", err)
	}

	return link_toc.Config{
		TocProvider: llmProvider,
		DebugAgents: debugAgents,
		Force:       false, // Set by caller if needed
	}, nil
}

// FinalizeTocConfig builds a finalize_toc.Config from the store.
func (b *Builder) FinalizeTocConfig(ctx context.Context) (finalize_toc.Config, error) {
	llmProvider, err := b.getString(ctx, "defaults.llm_provider")
	if err != nil {
		return finalize_toc.Config{}, fmt.Errorf("failed to get llm_provider: %w", err)
	}

	debugAgents, err := b.getBool(ctx, "defaults.debug_agents")
	if err != nil {
		return finalize_toc.Config{}, fmt.Errorf("failed to get debug_agents: %w", err)
	}

	return finalize_toc.Config{
		TocProvider: llmProvider,
		DebugAgents: debugAgents,
	}, nil
}

// CommonStructureConfig builds a common_structure.Config from the store.
func (b *Builder) CommonStructureConfig(ctx context.Context) (common_structure.Config, error) {
	llmProvider, err := b.getString(ctx, "defaults.llm_provider")
	if err != nil {
		return common_structure.Config{}, fmt.Errorf("failed to get llm_provider: %w", err)
	}

	debugAgents, err := b.getBool(ctx, "defaults.debug_agents")
	if err != nil {
		return common_structure.Config{}, fmt.Errorf("failed to get debug_agents: %w", err)
	}

	return common_structure.Config{
		StructureProvider: llmProvider,
		DebugAgents:       debugAgents,
	}, nil
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
			return s, nil
		}
		return "", fmt.Errorf("default for %q is not a string", key)
	}
	if s, ok := entry.Value.(string); ok {
		return s, nil
	}
	return "", fmt.Errorf("value for %q is not a string: %T", key, entry.Value)
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
			return v, nil
		}
		return false, fmt.Errorf("default for %q is not a bool", key)
	}
	if v, ok := entry.Value.(bool); ok {
		return v, nil
	}
	return false, fmt.Errorf("value for %q is not a bool: %T", key, entry.Value)
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
			return s, nil
		}
		return nil, fmt.Errorf("default for %q is not a string slice", key)
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
				return nil, fmt.Errorf("value for %q contains non-string item: %T", key, item)
			}
		}
		return result, nil
	default:
		return nil, fmt.Errorf("value for %q is not a string slice: %T", key, entry.Value)
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
		return toInt(def.Value, key)
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
		return 0, fmt.Errorf("value for %q is not an int: %T", key, v)
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

// OcrBookJobFactory returns a JobFactory that reads config from the store.
func OcrBookJobFactory(store config.Store) jobs.JobFactory {
	return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
		builder := NewBuilder(store)
		cfg, err := builder.OcrBookConfig(ctx)
		if err != nil {
			return nil, fmt.Errorf("failed to build config: %w", err)
		}
		return ocr_book.NewJob(ctx, cfg, bookID)
	})
}

// LabelBookJobFactory returns a JobFactory that reads config from the store.
func LabelBookJobFactory(store config.Store) jobs.JobFactory {
	return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
		builder := NewBuilder(store)
		cfg, err := builder.LabelBookConfig(ctx)
		if err != nil {
			return nil, fmt.Errorf("failed to build config: %w", err)
		}
		return label_book.NewJob(ctx, cfg, bookID)
	})
}

// MetadataBookJobFactory returns a JobFactory that reads config from the store.
func MetadataBookJobFactory(store config.Store) jobs.JobFactory {
	return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
		builder := NewBuilder(store)
		cfg, err := builder.MetadataBookConfig(ctx)
		if err != nil {
			return nil, fmt.Errorf("failed to build config: %w", err)
		}
		return metadata_book.NewJob(ctx, cfg, bookID)
	})
}

// TocBookJobFactory returns a JobFactory that reads config from the store.
func TocBookJobFactory(store config.Store) jobs.JobFactory {
	return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
		builder := NewBuilder(store)
		cfg, err := builder.TocBookConfig(ctx)
		if err != nil {
			return nil, fmt.Errorf("failed to build config: %w", err)
		}
		return toc_book.NewJob(ctx, cfg, bookID)
	})
}

// LinkTocJobFactory returns a JobFactory that reads config from the store.
func LinkTocJobFactory(store config.Store) jobs.JobFactory {
	return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
		builder := NewBuilder(store)
		cfg, err := builder.LinkTocConfig(ctx)
		if err != nil {
			return nil, fmt.Errorf("failed to build config: %w", err)
		}
		return link_toc.NewJob(ctx, cfg, bookID)
	})
}

// FinalizeTocJobFactory returns a JobFactory that reads config from the store.
func FinalizeTocJobFactory(store config.Store) jobs.JobFactory {
	return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
		builder := NewBuilder(store)
		cfg, err := builder.FinalizeTocConfig(ctx)
		if err != nil {
			return nil, fmt.Errorf("failed to build config: %w", err)
		}
		return finalize_toc.NewJob(ctx, cfg, bookID)
	})
}

// CommonStructureJobFactory returns a JobFactory that reads config from the store.
func CommonStructureJobFactory(store config.Store) jobs.JobFactory {
	return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
		builder := NewBuilder(store)
		cfg, err := builder.CommonStructureConfig(ctx)
		if err != nil {
			return nil, fmt.Errorf("failed to build config: %w", err)
		}
		return common_structure.NewJob(ctx, cfg, bookID)
	})
}

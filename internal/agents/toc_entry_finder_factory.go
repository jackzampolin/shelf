package agents

import (
	"context"

	"github.com/jackzampolin/shelf/internal/agent"
	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/agents/toc_entry_finder/tools"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/providers"
)

const tocEntryFinderMaxIterations = 25

// TocEntryFinderConfig configures ToC entry finder agent creation.
type TocEntryFinderConfig struct {
	Book          *common.BookState
	SystemPrompt  string
	Entry         *toc_entry_finder.TocEntry
	BookStructure *toc_entry_finder.BookStructure
	Debug         bool
	JobID         string
}

// NewTocEntryFinderAgent creates a configured ToC entry finder agent.
// The agent is ready for iteration via NextWorkUnits().
// Context is required for observability logging.
func NewTocEntryFinderAgent(ctx context.Context, cfg TocEntryFinderConfig) *agent.Agent {
	toolConfig := tools.Config{
		Book:  cfg.Book,
		Entry: cfg.Entry,
	}
	if cfg.BookStructure != nil {
		toolConfig.BackMatterStart = cfg.BookStructure.BackMatterStart
		toolConfig.BackMatterTypes = cfg.BookStructure.BackMatterTypes
		toolConfig.TargetIsBackMatter = cfg.BookStructure.TargetIsBackMatter
	}

	entryTools := tools.New(toolConfig)

	userPrompt := toc_entry_finder.BuildUserPrompt(cfg.Entry, cfg.Book.TotalPages, cfg.BookStructure)

	return agent.New(ctx, agent.Config{
		Tools:               entryTools,
		RequireToolUse:      true,
		MaxToolCallsPerTurn: 4,
		InitialMessages: []providers.Message{
			{Role: "system", Content: cfg.SystemPrompt},
			{Role: "user", Content: userPrompt},
		},
		MaxIterations: tocEntryFinderMaxIterations,
		AgentType:     "toc_entry_finder",
		BookID:        cfg.Book.BookID,
		JobID:         cfg.JobID,
		Debug:         cfg.Debug,
	})
}

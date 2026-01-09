package agents

import (
	"context"

	"github.com/jackzampolin/shelf/internal/agent"
	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/agents/toc_entry_finder/tools"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/providers"
)

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
	entryTools := tools.New(tools.Config{
		Book:  cfg.Book,
		Entry: cfg.Entry,
	})

	userPrompt := toc_entry_finder.BuildUserPrompt(cfg.Entry, cfg.Book.TotalPages, cfg.BookStructure)

	// Build agent ID from entry info for tracing
	agentID := "entry"
	if cfg.Entry.EntryNumber != "" {
		agentID += "-" + cfg.Entry.EntryNumber
	}
	if cfg.Entry.LevelName != "" {
		agentID = cfg.Entry.LevelName + "-" + agentID
	}

	return agent.New(ctx, agent.Config{
		ID:    agentID,
		Tools: entryTools,
		InitialMessages: []providers.Message{
			{Role: "system", Content: cfg.SystemPrompt},
			{Role: "user", Content: userPrompt},
		},
		MaxIterations: 15, // Entry finding should be quick
		AgentType:     "toc_entry_finder",
		BookID:        cfg.Book.BookID,
		JobID:         cfg.JobID,
		Debug:         cfg.Debug,
	})
}

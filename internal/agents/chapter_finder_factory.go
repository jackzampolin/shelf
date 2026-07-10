package agents

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/agent"
	chapter_finder "github.com/jackzampolin/shelf/internal/agents/chapter_finder"
	"github.com/jackzampolin/shelf/internal/agents/chapter_finder/tools"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/providers"
)

// ChapterFinderConfig configures chapter finder agent creation.
type ChapterFinderConfig struct {
	Book           *common.BookState
	SystemPrompt   string
	Entry          *chapter_finder.EntryToFind
	ExcludedRanges []chapter_finder.ExcludedRange
	Debug          bool
	JobID          string
}

// NewChapterFinderAgent creates a configured chapter finder agent.
// The agent is ready for iteration via NextWorkUnits().
// Context is required for observability logging.
func NewChapterFinderAgent(ctx context.Context, cfg ChapterFinderConfig) *agent.Agent {
	finderTools := tools.New(tools.Config{
		Book:           cfg.Book,
		Entry:          cfg.Entry,
		ExcludedRanges: cfg.ExcludedRanges,
	})

	userPrompt := chapter_finder.BuildUserPrompt(cfg.Entry, cfg.Book.TotalPages, cfg.ExcludedRanges)

	// Keep the deterministic ID stable for crash recovery but scope it to the
	// book. Entry labels repeat across nearly every book (for example
	// "chapter--1"), so an unscoped ID aliases durable AgentState records.
	agentID := fmt.Sprintf("chapter-%s-%s-%s", cfg.Book.BookID, cfg.Entry.LevelName, cfg.Entry.Identifier)

	return agent.New(ctx, agent.Config{
		ID:    agentID,
		Tools: finderTools,
		InitialMessages: []providers.Message{
			{Role: "system", Content: cfg.SystemPrompt},
			{Role: "user", Content: userPrompt},
		},
		MaxIterations: 15, // Chapter finding should be quick
		AgentType:     "chapter_finder",
		BookID:        cfg.Book.BookID,
		JobID:         cfg.JobID,
		Debug:         cfg.Debug,
	})
}

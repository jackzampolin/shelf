package agents

import (
	"context"

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

	// Let agent.New allocate a fresh ID. DefraDB tombstones deleted documents,
	// so reusing a deterministic ID after successful cleanup prevents a later
	// run from persisting its resumable state. Resume restores the saved ID.
	return agent.New(ctx, agent.Config{
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

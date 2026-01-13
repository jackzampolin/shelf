package agents

import (
	"context"

	"github.com/jackzampolin/shelf/internal/agent"
	toc_finder "github.com/jackzampolin/shelf/internal/agents/toc_finder"
	"github.com/jackzampolin/shelf/internal/agents/toc_finder/tools"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/providers"
)

// TocFinderConfig configures ToC finder agent creation.
type TocFinderConfig struct {
	Book         *common.BookState
	SystemPrompt string
	Debug        bool
	JobID        string
}

// NewTocFinderAgent creates a configured ToC finder agent.
// The agent is ready for iteration via NextWorkUnits().
// Context is required for observability logging (creating initial "running" record).
func NewTocFinderAgent(ctx context.Context, cfg TocFinderConfig) *agent.Agent {
	tocTools := tools.New(tools.Config{
		Book: cfg.Book,
	})

	userPrompt := toc_finder.BuildUserPrompt(cfg.Book.BookID, cfg.Book.GetBookTitle(), cfg.Book.TotalPages, nil)

	return agent.New(ctx, agent.Config{
		Tools: tocTools,
		InitialMessages: []providers.Message{
			{Role: "system", Content: cfg.SystemPrompt},
			{Role: "user", Content: userPrompt},
		},
		MaxIterations: 25,
		AgentType:     "toc_finder",
		BookID:        cfg.Book.BookID,
		JobID:         cfg.JobID,
		Debug:         cfg.Debug,
	})
}

package agents

import (
	"context"

	"github.com/jackzampolin/shelf/internal/agent"
	toc_finder "github.com/jackzampolin/shelf/internal/agents/toc_finder"
	"github.com/jackzampolin/shelf/internal/agents/toc_finder/tools"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/providers"
)

// TocFinderConfig configures ToC finder agent creation.
type TocFinderConfig struct {
	BookID       string
	BookTitle    string // From metadata, may be empty
	TotalPages   int
	DefraClient  *defra.Client
	HomeDir      *home.Dir
	PageReader   common.PageDataReader // Optional: cached page data access
	SystemPrompt string
	Debug        bool
	JobID        string
}

// NewTocFinderAgent creates a configured ToC finder agent.
// The agent is ready for iteration via NextWorkUnits().
// Context is required for observability logging (creating initial "running" record).
func NewTocFinderAgent(ctx context.Context, cfg TocFinderConfig) *agent.Agent {
	tocTools := tools.New(tools.Config{
		BookID:      cfg.BookID,
		TotalPages:  cfg.TotalPages,
		DefraClient: cfg.DefraClient,
		HomeDir:     cfg.HomeDir,
		PageReader:  cfg.PageReader,
	})

	userPrompt := toc_finder.BuildUserPrompt(cfg.BookID, cfg.BookTitle, cfg.TotalPages, nil)

	return agent.New(ctx, agent.Config{
		Tools: tocTools,
		InitialMessages: []providers.Message{
			{Role: "system", Content: cfg.SystemPrompt},
			{Role: "user", Content: userPrompt},
		},
		MaxIterations: 25,
		AgentType:     "toc_finder",
		BookID:        cfg.BookID,
		JobID:         cfg.JobID,
		Debug:         cfg.Debug,
	})
}

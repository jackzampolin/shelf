package agents

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/agent"
	gap_investigator "github.com/jackzampolin/shelf/internal/agents/gap_investigator"
	"github.com/jackzampolin/shelf/internal/agents/gap_investigator/tools"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/providers"
)

// GapInvestigatorConfig configures gap investigator agent creation.
type GapInvestigatorConfig struct {
	Book          *common.BookState
	SystemPrompt  string
	Gap           *gap_investigator.GapInfo
	LinkedEntries []*gap_investigator.LinkedEntry
	Debug         bool
	JobID         string
}

// NewGapInvestigatorAgent creates a configured gap investigator agent.
// The agent is ready for iteration via NextWorkUnits().
// Context is required for observability logging.
func NewGapInvestigatorAgent(ctx context.Context, cfg GapInvestigatorConfig) *agent.Agent {
	gapTools := tools.New(tools.Config{
		Book:          cfg.Book,
		Gap:           cfg.Gap,
		LinkedEntries: cfg.LinkedEntries,
	})

	userPrompt := gap_investigator.BuildUserPrompt(cfg.Gap, cfg.Book.BodyStart, cfg.Book.BodyEnd, cfg.Book.TotalPages)

	// Build agent ID from gap info for tracing
	agentID := fmt.Sprintf("gap-%d-%d", cfg.Gap.StartPage, cfg.Gap.EndPage)

	return agent.New(ctx, agent.Config{
		ID:    agentID,
		Tools: gapTools,
		InitialMessages: []providers.Message{
			{Role: "system", Content: cfg.SystemPrompt},
			{Role: "user", Content: userPrompt},
		},
		MaxIterations: 20, // Gap investigation may need more exploration
		AgentType:     "gap_investigator",
		BookID:        cfg.Book.BookID,
		JobID:         cfg.JobID,
		Debug:         cfg.Debug,
	})
}

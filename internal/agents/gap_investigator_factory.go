package agents

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/agent"
	gap_investigator "github.com/jackzampolin/shelf/internal/agents/gap_investigator"
	"github.com/jackzampolin/shelf/internal/agents/gap_investigator/tools"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/providers"
)

// GapInvestigatorConfig configures gap investigator agent creation.
type GapInvestigatorConfig struct {
	BookID        string
	TotalPages    int
	DefraClient   *defra.Client
	HomeDir       *home.Dir
	SystemPrompt  string
	Gap           *gap_investigator.GapInfo
	LinkedEntries []*gap_investigator.LinkedEntry
	BodyStart     int
	BodyEnd       int
	Debug         bool
	JobID         string
}

// NewGapInvestigatorAgent creates a configured gap investigator agent.
// The agent is ready for iteration via NextWorkUnits().
// Context is required for observability logging.
func NewGapInvestigatorAgent(ctx context.Context, cfg GapInvestigatorConfig) *agent.Agent {
	gapTools := tools.New(tools.Config{
		BookID:        cfg.BookID,
		TotalPages:    cfg.TotalPages,
		DefraClient:   cfg.DefraClient,
		HomeDir:       cfg.HomeDir,
		Gap:           cfg.Gap,
		LinkedEntries: cfg.LinkedEntries,
		BodyStart:     cfg.BodyStart,
		BodyEnd:       cfg.BodyEnd,
	})

	userPrompt := gap_investigator.BuildUserPrompt(cfg.Gap, cfg.BodyStart, cfg.BodyEnd, cfg.TotalPages)

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
		BookID:        cfg.BookID,
		JobID:         cfg.JobID,
		Debug:         cfg.Debug,
	})
}

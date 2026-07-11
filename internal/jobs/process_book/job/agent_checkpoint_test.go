package job

import (
	"context"
	"testing"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/providers"
)

type checkpointTestTools struct{}

func (checkpointTestTools) GetTools() []providers.Tool { return nil }
func (checkpointTestTools) ExecuteTool(context.Context, string, map[string]any) (string, error) {
	return `{}`, nil
}
func (checkpointTestTools) IsComplete() bool    { return false }
func (checkpointTestTools) GetImages() [][]byte { return nil }
func (checkpointTestTools) GetResult() any      { return nil }

func TestCheckpointAgentStatePersistsConversationForNextIteration(t *testing.T) {
	store := common.NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})
	book := common.NewBookState("book-1")
	book.Store = store
	j := NewFromLoadResult(&common.LoadBookResult{Book: book})

	ag := agent.New(context.Background(), agent.Config{
		ID:    "agent-1",
		Tools: checkpointTestTools{},
		InitialMessages: []providers.Message{
			{Role: "system", Content: "Use tools."},
			{Role: "user", Content: "Find the page."},
		},
		MaxIterations: 5,
	})
	if units := ag.NextWorkUnits(); len(units) != 1 || units[0].Iteration != 1 {
		t.Fatalf("first work units = %#v, want iteration 1", units)
	}
	ag.HandleLLMResult(&providers.ChatResult{Content: "I will keep looking."})

	if err := j.checkpointAgentState(context.Background(), ag, common.AgentTypeTocEntryFinder, "entry-1"); err != nil {
		t.Fatal(err)
	}
	saved := book.GetAgentState(common.AgentTypeTocEntryFinder, "entry-1")
	if saved == nil {
		t.Fatal("checkpoint was not stored in memory")
	}
	if saved.Iteration != 1 {
		t.Fatalf("saved iteration = %d, want 1", saved.Iteration)
	}
	if saved.MessagesJSON == "" || saved.MessagesJSON == "[]" {
		t.Fatalf("saved messages are empty: %q", saved.MessagesJSON)
	}
	stored := store.GetDoc("AgentState", saved.DocID)
	if stored == nil || stored["iteration"] != 1 {
		t.Fatalf("durable checkpoint = %#v, want iteration 1", stored)
	}

	resumed := agent.New(context.Background(), agent.Config{Tools: checkpointTestTools{}, MaxIterations: 5})
	if err := resumed.RestoreState(&agent.StateExport{
		AgentID:          saved.AgentID,
		Iteration:        saved.Iteration,
		Complete:         saved.Complete,
		MessagesJSON:     saved.MessagesJSON,
		PendingToolCalls: saved.PendingToolCalls,
		ToolResults:      saved.ToolResults,
		ResultJSON:       saved.ResultJSON,
	}); err != nil {
		t.Fatal(err)
	}
	if units := resumed.NextWorkUnits(); len(units) != 1 || units[0].Iteration != 2 {
		t.Fatalf("resumed work units = %#v, want iteration 2", units)
	}
}

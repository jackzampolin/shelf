package agent

import (
	"context"
	"strings"
	"sync"
	"testing"

	"github.com/jackzampolin/shelf/internal/providers"
)

// mockTools is a simple mock for unit testing
type mockTools struct {
	mu       sync.Mutex
	tools    []providers.Tool
	complete bool
	result   any
}

func (m *mockTools) GetTools() []providers.Tool {
	return m.tools
}

func (m *mockTools) ExecuteTool(ctx context.Context, name string, args map[string]any) (string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if name == "done" {
		m.complete = true
		m.result = "completed"
	}
	return `{"status": "ok"}`, nil
}

func (m *mockTools) IsComplete() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.complete
}

func (m *mockTools) GetImages() [][]byte {
	return nil
}

func (m *mockTools) GetResult() any {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.result
}

func TestAgent_NextWorkUnits_RequireToolUse(t *testing.T) {
	tools := &mockTools{
		tools: []providers.Tool{
			{Type: "function", Function: providers.ToolFunction{Name: "grep_text"}},
		},
	}
	agent := New(context.Background(), Config{
		ID:             "tool-required-agent",
		Tools:          tools,
		RequireToolUse: true,
		InitialMessages: []providers.Message{
			{Role: "system", Content: "Use tools."},
			{Role: "user", Content: "Find the page."},
		},
		MaxIterations: 10,
	})

	units := agent.NextWorkUnits()
	if len(units) != 1 {
		t.Fatalf("NextWorkUnits() len = %d, want 1", len(units))
	}
	if units[0].ChatRequest == nil {
		t.Fatal("ChatRequest is nil")
	}
	if units[0].ChatRequest.ToolChoice != "required" {
		t.Fatalf("ToolChoice = %#v, want required", units[0].ChatRequest.ToolChoice)
	}
}

func TestAgent_HandleLLMResult_MaxToolCallsPerTurn(t *testing.T) {
	tools := &mockTools{
		tools: []providers.Tool{
			{Type: "function", Function: providers.ToolFunction{Name: "get_page_ocr"}},
		},
	}
	agent := New(context.Background(), Config{
		ID:                  "tool-cap-agent",
		Tools:               tools,
		MaxToolCallsPerTurn: 2,
		MaxIterations:       10,
	})

	result := &providers.ChatResult{
		ToolCalls: []providers.ToolCall{
			{ID: "call_1", Type: "function"},
			{ID: "call_2", Type: "function"},
			{ID: "call_3", Type: "function"},
		},
	}
	result.ToolCalls[0].Function.Name = "get_page_ocr"
	result.ToolCalls[0].Function.Arguments = `{"page_num":1}`
	result.ToolCalls[1].Function.Name = "get_page_ocr"
	result.ToolCalls[1].Function.Arguments = `{"page_num":2}`
	result.ToolCalls[2].Function.Name = "get_page_ocr"
	result.ToolCalls[2].Function.Arguments = `{"page_num":3}`

	agent.HandleLLMResult(result)

	units := agent.NextWorkUnits()
	if len(units) != 2 {
		t.Fatalf("NextWorkUnits() len = %d, want 2", len(units))
	}
	if units[0].ToolCall.ID != "call_1" || units[1].ToolCall.ID != "call_2" {
		t.Fatalf("tool calls = %s, %s; want call_1, call_2", units[0].ToolCall.ID, units[1].ToolCall.ID)
	}
}

func TestAgent_NextWorkUnits_CompactsOldToolResultsForRequestOnly(t *testing.T) {
	longToolResult := strings.Repeat("large tool payload ", 80)
	tools := &mockTools{
		tools: []providers.Tool{
			{Type: "function", Function: providers.ToolFunction{Name: "get_page_ocr"}},
		},
	}
	agent := New(context.Background(), Config{
		ID:    "compact-history-agent",
		Tools: tools,
		InitialMessages: []providers.Message{
			{Role: "system", Content: "Use tools."},
			{Role: "user", Content: "Find the page."},
		},
		MaxIterations: 10,
	})

	agent.mu.Lock()
	for i := 0; i < 12; i++ {
		agent.messages = append(agent.messages,
			providers.Message{Role: "assistant", Content: "calling tool"},
			providers.Message{Role: "tool", ToolCallID: "call", Content: longToolResult},
		)
	}
	originalStoredContent := agent.messages[3].Content
	agent.mu.Unlock()

	units := agent.NextWorkUnits()
	if len(units) != 1 || units[0].ChatRequest == nil {
		t.Fatalf("NextWorkUnits returned %#v, want one LLM request", units)
	}
	requestMessages := units[0].ChatRequest.Messages
	if got := requestMessages[3].Content; !strings.Contains(got, "older tool result compacted") {
		t.Fatalf("old tool result was not compacted: %q", got)
	}
	if len([]rune(requestMessages[len(requestMessages)-1].Content)) != len([]rune(longToolResult)) {
		t.Fatal("most recent tool result should remain full in the outbound request")
	}
	if agent.messages[3].Content != originalStoredContent {
		t.Fatal("agent stored history was mutated by request compaction")
	}
}

// TestAgent_ExportState_RestoreState_RoundTrip tests that agent state can be
// serialized and restored correctly for job resume functionality.
func TestAgent_ExportState_RestoreState_RoundTrip(t *testing.T) {
	ctx := context.Background()

	t.Run("basic_round_trip", func(t *testing.T) {
		// Create an agent with initial messages
		tools := &mockTools{
			tools: []providers.Tool{
				{Type: "function", Function: providers.ToolFunction{Name: "test_tool"}},
			},
		}
		agent1 := New(ctx, Config{
			ID:    "test-agent-1",
			Tools: tools,
			InitialMessages: []providers.Message{
				{Role: "system", Content: "You are a helpful assistant."},
				{Role: "user", Content: "Hello!"},
			},
			MaxIterations: 10,
		})

		// Simulate some conversation by adding messages manually
		// (normally done by ProcessResponse, but we test state directly)
		agent1.mu.Lock()
		agent1.messages = append(agent1.messages, providers.Message{
			Role:    "assistant",
			Content: "Hello! How can I help?",
		})
		agent1.iteration = 3
		agent1.mu.Unlock()

		// Export state
		exported, err := agent1.ExportState()
		if err != nil {
			t.Fatalf("ExportState() error = %v", err)
		}

		// Verify exported state
		if exported.AgentID != "test-agent-1" {
			t.Errorf("AgentID = %s, want test-agent-1", exported.AgentID)
		}
		if exported.Iteration != 3 {
			t.Errorf("Iteration = %d, want 3", exported.Iteration)
		}
		if exported.Complete {
			t.Error("Complete should be false")
		}
		if exported.MessagesJSON == "" {
			t.Error("MessagesJSON should not be empty")
		}

		// Create a new agent and restore state
		agent2 := New(ctx, Config{
			ID:            "test-agent-2", // Different ID
			Tools:         tools,
			MaxIterations: 10,
		})

		if err := agent2.RestoreState(exported); err != nil {
			t.Fatalf("RestoreState() error = %v", err)
		}

		// Verify restored state
		agent2.mu.Lock()
		if agent2.iteration != 3 {
			t.Errorf("restored iteration = %d, want 3", agent2.iteration)
		}
		if len(agent2.messages) != 3 {
			t.Errorf("restored messages count = %d, want 3", len(agent2.messages))
		}
		if agent2.messages[2].Content != "Hello! How can I help?" {
			t.Errorf("restored message content = %s, want 'Hello! How can I help?'", agent2.messages[2].Content)
		}
		agent2.mu.Unlock()
	})

	t.Run("with_pending_tool_calls", func(t *testing.T) {
		tools := &mockTools{
			tools: []providers.Tool{
				{Type: "function", Function: providers.ToolFunction{Name: "get_data"}},
			},
		}
		agent1 := New(ctx, Config{
			ID:            "tool-agent",
			Tools:         tools,
			MaxIterations: 10,
		})

		// Simulate pending tool calls
		agent1.mu.Lock()
		agent1.pendingToolCalls = []providers.ToolCall{
			{ID: "call_123", Function: struct {
				Name      string `json:"name"`
				Arguments string `json:"arguments"`
			}{Name: "get_data", Arguments: `{"key": "value"}`}},
			{ID: "call_456", Function: struct {
				Name      string `json:"name"`
				Arguments string `json:"arguments"`
			}{Name: "get_data", Arguments: `{"key": "value2"}`}},
		}
		agent1.toolResults = map[string]string{
			"call_123": `{"result": "data1"}`,
		}
		agent1.mu.Unlock()

		// Export
		exported, err := agent1.ExportState()
		if err != nil {
			t.Fatalf("ExportState() error = %v", err)
		}

		if exported.PendingToolCalls == "" {
			t.Error("PendingToolCalls should not be empty")
		}
		if exported.ToolResults == "" {
			t.Error("ToolResults should not be empty")
		}

		// Restore to new agent
		agent2 := New(ctx, Config{
			ID:            "tool-agent-2",
			Tools:         tools,
			MaxIterations: 10,
		})

		if err := agent2.RestoreState(exported); err != nil {
			t.Fatalf("RestoreState() error = %v", err)
		}

		// Verify
		agent2.mu.Lock()
		if len(agent2.pendingToolCalls) != 2 {
			t.Errorf("restored pendingToolCalls count = %d, want 2", len(agent2.pendingToolCalls))
		}
		if agent2.pendingToolCalls[0].ID != "call_123" {
			t.Errorf("restored tool call ID = %s, want call_123", agent2.pendingToolCalls[0].ID)
		}
		if agent2.toolResults["call_123"] != `{"result": "data1"}` {
			t.Errorf("restored tool result = %s, want '{\"result\": \"data1\"}'", agent2.toolResults["call_123"])
		}
		agent2.mu.Unlock()
	})

	t.Run("with_completed_result", func(t *testing.T) {
		tools := &mockTools{
			tools: []providers.Tool{
				{Type: "function", Function: providers.ToolFunction{Name: "complete"}},
			},
		}
		agent1 := New(ctx, Config{
			ID:            "completed-agent",
			Tools:         tools,
			MaxIterations: 10,
		})

		// Simulate completion
		agent1.mu.Lock()
		agent1.complete = true
		agent1.result = &Result{
			Success:    true,
			Iterations: 5,
			ToolResult: "final answer",
		}
		agent1.mu.Unlock()

		// Export
		exported, err := agent1.ExportState()
		if err != nil {
			t.Fatalf("ExportState() error = %v", err)
		}

		if !exported.Complete {
			t.Error("Complete should be true")
		}
		if exported.ResultJSON == "" {
			t.Error("ResultJSON should not be empty for completed agent")
		}

		// Restore
		agent2 := New(ctx, Config{
			ID:            "completed-agent-2",
			Tools:         tools,
			MaxIterations: 10,
		})

		if err := agent2.RestoreState(exported); err != nil {
			t.Fatalf("RestoreState() error = %v", err)
		}

		agent2.mu.Lock()
		if !agent2.complete {
			t.Error("restored complete should be true")
		}
		if agent2.result == nil {
			t.Error("restored result should not be nil")
		} else if !agent2.result.Success {
			t.Error("restored result.Success should be true")
		}
		agent2.mu.Unlock()
	})

	t.Run("empty_state", func(t *testing.T) {
		tools := &mockTools{}
		agent1 := New(ctx, Config{
			ID:            "empty-agent",
			Tools:         tools,
			MaxIterations: 5,
		})

		exported, err := agent1.ExportState()
		if err != nil {
			t.Fatalf("ExportState() error = %v", err)
		}

		agent2 := New(ctx, Config{
			ID:            "empty-agent-2",
			Tools:         tools,
			MaxIterations: 5,
		})

		if err := agent2.RestoreState(exported); err != nil {
			t.Fatalf("RestoreState() error = %v", err)
		}

		// Should not error on empty state
		agent2.mu.Lock()
		if agent2.iteration != 0 {
			t.Errorf("iteration = %d, want 0", agent2.iteration)
		}
		agent2.mu.Unlock()
	})

	t.Run("malformed_json_errors", func(t *testing.T) {
		tools := &mockTools{}
		agent := New(ctx, Config{
			ID:            "test",
			Tools:         tools,
			MaxIterations: 5,
		})

		// Test with malformed messages JSON
		err := agent.RestoreState(&StateExport{
			MessagesJSON: "not valid json",
		})
		if err == nil {
			t.Error("RestoreState should error on malformed MessagesJSON")
		}

		// Test with malformed tool calls JSON
		err = agent.RestoreState(&StateExport{
			MessagesJSON:     "[]",
			PendingToolCalls: "not valid json",
		})
		if err == nil {
			t.Error("RestoreState should error on malformed PendingToolCalls")
		}

		// Test with malformed tool results JSON
		err = agent.RestoreState(&StateExport{
			MessagesJSON: "[]",
			ToolResults:  "not valid json",
		})
		if err == nil {
			t.Error("RestoreState should error on malformed ToolResults")
		}

		// Test with malformed result JSON
		err = agent.RestoreState(&StateExport{
			MessagesJSON: "[]",
			ResultJSON:   "not valid json",
		})
		if err == nil {
			t.Error("RestoreState should error on malformed ResultJSON")
		}
	})
}

package agent

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/providers"
)

// Integration tests for the agent system.
// These tests make real API calls and require OPENROUTER_API_KEY.

func TestAgentIntegration_SingleAgent(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}
	apiKey := os.Getenv("OPENROUTER_API_KEY")
	if apiKey == "" {
		t.Skip("OPENROUTER_API_KEY not set")
	}

	// Create temp directory for file operations
	tmpDir := t.TempDir()

	// Create some initial files
	os.WriteFile(filepath.Join(tmpDir, "input.txt"), []byte("Hello World"), 0644)
	os.WriteFile(filepath.Join(tmpDir, "numbers.txt"), []byte("1\n2\n3\n4\n5"), 0644)

	// Create tools and agent
	tools := NewFileTools(tmpDir)
	agentJob := NewAgentJobFromConfig(AgentJobConfig{
		ID:    "test-agent-1",
		Tools: tools,
		InitialMessages: []providers.Message{
			{
				Role: "system",
				Content: `You are a file assistant. You have access to a directory with some files.
Use the tools to explore the files and complete the task.
When done, use the complete tool with your final answer.`,
			},
			{
				Role: "user",
				Content: `Please:
1. List the files in the current directory
2. Read the contents of input.txt
3. Create a new file called output.txt containing the text from input.txt but in UPPERCASE
4. Report what you did using the complete tool`,
			},
		},
		MaxIterations: 10,
	})

	// Create OpenRouter client
	client := providers.NewOpenRouterClient(providers.OpenRouterConfig{
		APIKey:       apiKey,
		DefaultModel: "x-ai/grok-4.1-fast",
	})

	// Create pool
	pool, err := jobs.NewProviderWorkerPool(jobs.ProviderWorkerPoolConfig{
		Name:      "openrouter",
		LLMClient: client,
		RPS:       1.0,
	})
	if err != nil {
		t.Fatalf("failed to create pool: %v", err)
	}

	// Create scheduler (no persistence for tests)
	scheduler := jobs.NewScheduler(jobs.SchedulerConfig{})
	scheduler.RegisterPool(pool)

	// Start scheduler (runs workers as goroutines internally)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	go scheduler.Start(ctx)

	// Submit job
	if err := scheduler.Submit(ctx, agentJob); err != nil {
		t.Fatalf("failed to submit job: %v", err)
	}

	// Wait for completion
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			t.Fatal("test timed out")
		case <-ticker.C:
			if agentJob.Done() {
				goto done
			}
		}
	}
done:

	// Check result
	result := agentJob.Result()
	if result == nil {
		t.Fatal("expected result")
	}
	if !result.Success {
		t.Errorf("agent failed: %s", result.Error)
	}

	t.Logf("Agent completed in %d iterations", result.Iterations)
	t.Logf("Result: %v", result.ToolResult)

	// Verify output file was created
	outputContent, err := os.ReadFile(filepath.Join(tmpDir, "output.txt"))
	if err != nil {
		t.Errorf("output.txt not created: %v", err)
	} else {
		if !strings.Contains(strings.ToUpper(string(outputContent)), "HELLO") {
			t.Errorf("output.txt should contain uppercase content, got: %s", outputContent)
		}
		t.Logf("output.txt content: %s", outputContent)
	}
}

func TestAgentIntegration_MultipleAgents(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}
	apiKey := os.Getenv("OPENROUTER_API_KEY")
	if apiKey == "" {
		t.Skip("OPENROUTER_API_KEY not set")
	}

	// Create 3 agents with different tasks
	type agentTask struct {
		name    string
		task    string
		setup   func(dir string)
		verify  func(t *testing.T, dir string)
	}

	tasks := []agentTask{
		{
			name: "counter",
			task: "Count the number of lines in data.txt and write the count to count.txt, then complete with the count.",
			setup: func(dir string) {
				os.WriteFile(filepath.Join(dir, "data.txt"), []byte("line1\nline2\nline3\nline4\nline5\nline6\nline7"), 0644)
			},
			verify: func(t *testing.T, dir string) {
				content, err := os.ReadFile(filepath.Join(dir, "count.txt"))
				if err != nil {
					t.Errorf("counter: count.txt not created: %v", err)
					return
				}
				t.Logf("counter: count.txt = %s", strings.TrimSpace(string(content)))
			},
		},
		{
			name: "reverser",
			task: "Read the text in source.txt, reverse the characters, and write to reversed.txt, then complete.",
			setup: func(dir string) {
				os.WriteFile(filepath.Join(dir, "source.txt"), []byte("Hello World"), 0644)
			},
			verify: func(t *testing.T, dir string) {
				content, err := os.ReadFile(filepath.Join(dir, "reversed.txt"))
				if err != nil {
					t.Errorf("reverser: reversed.txt not created: %v", err)
					return
				}
				t.Logf("reverser: reversed.txt = %s", strings.TrimSpace(string(content)))
			},
		},
		{
			name: "summarizer",
			task: "List all files in the directory and write a summary of what files exist to summary.txt, then complete.",
			setup: func(dir string) {
				os.WriteFile(filepath.Join(dir, "file1.txt"), []byte("content1"), 0644)
				os.WriteFile(filepath.Join(dir, "file2.txt"), []byte("content2"), 0644)
				os.Mkdir(filepath.Join(dir, "subdir"), 0755)
			},
			verify: func(t *testing.T, dir string) {
				content, err := os.ReadFile(filepath.Join(dir, "summary.txt"))
				if err != nil {
					t.Errorf("summarizer: summary.txt not created: %v", err)
					return
				}
				t.Logf("summarizer: summary.txt = %s", strings.TrimSpace(string(content)))
			},
		},
	}

	// Create temp dirs and agent jobs
	var agentJobs []*AgentJob
	var tmpDirs []string

	for _, task := range tasks {
		tmpDir := t.TempDir()
		tmpDirs = append(tmpDirs, tmpDir)
		task.setup(tmpDir)

		tools := NewFileTools(tmpDir)
		agentJob := NewAgentJobFromConfig(AgentJobConfig{
			ID:    task.name,
			Tools: tools,
			InitialMessages: []providers.Message{
				{
					Role: "system",
					Content: `You are a file assistant. Use the tools to complete the task.
When done, use the complete tool with your result.`,
				},
				{
					Role:    "user",
					Content: task.task,
				},
			},
			MaxIterations: 8,
		})
		agentJobs = append(agentJobs, agentJob)
	}

	// Create OpenRouter client
	client := providers.NewOpenRouterClient(providers.OpenRouterConfig{
		APIKey:       apiKey,
		DefaultModel: "x-ai/grok-4.1-fast",
	})

	// Create pool
	pool, err := jobs.NewProviderWorkerPool(jobs.ProviderWorkerPoolConfig{
		Name:      "openrouter",
		LLMClient: client,
		RPS:       1.0,
	})
	if err != nil {
		t.Fatalf("failed to create pool: %v", err)
	}

	// Create scheduler
	scheduler := jobs.NewScheduler(jobs.SchedulerConfig{})
	scheduler.RegisterPool(pool)

	// Start scheduler - pools run as their own goroutines
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Minute)
	defer cancel()

	go scheduler.Start(ctx)

	// Submit all jobs
	for _, job := range agentJobs {
		if err := scheduler.Submit(ctx, job); err != nil {
			t.Fatalf("failed to submit job: %v", err)
		}
	}

	t.Logf("Submitted %d agent jobs", len(agentJobs))

	// Wait for all to complete
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			t.Fatal("test timed out")
		case <-ticker.C:
			allDone := true
			for _, job := range agentJobs {
				if !job.Done() {
					allDone = false
					break
				}
			}
			if allDone {
				goto done
			}
		}
	}
done:

	// Check results
	for i, job := range agentJobs {
		result := job.Result()
		if result == nil {
			t.Errorf("agent %s: no result", tasks[i].name)
			continue
		}

		t.Logf("Agent %s: success=%t iterations=%d result=%v",
			tasks[i].name, result.Success, result.Iterations, result.ToolResult)

		if !result.Success {
			t.Errorf("agent %s failed: %s", tasks[i].name, result.Error)
		}

		// Run verification
		tasks[i].verify(t, tmpDirs[i])
	}
}

func TestAgentIntegration_MaxIterations(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}
	apiKey := os.Getenv("OPENROUTER_API_KEY")
	if apiKey == "" {
		t.Skip("OPENROUTER_API_KEY not set")
	}

	// Create agent with an impossible task and low max iterations
	tmpDir := t.TempDir()
	tools := NewFileTools(tmpDir)

	agentJob := NewAgentJobFromConfig(AgentJobConfig{
		ID:    "impossible-task",
		Tools: tools,
		InitialMessages: []providers.Message{
			{
				Role: "system",
				Content: `You are a file assistant. Use tools to complete tasks.`,
			},
			{
				Role: "user",
				Content: `Find the file called "nonexistent.txt" and read its contents.
Keep searching until you find it. Do not give up.`,
			},
		},
		MaxIterations: 3, // Low limit to trigger max iterations
	})

	// Create OpenRouter client
	client := providers.NewOpenRouterClient(providers.OpenRouterConfig{
		APIKey:       apiKey,
		DefaultModel: "x-ai/grok-4.1-fast",
	})

	// Create pool and scheduler
	pool, _ := jobs.NewProviderWorkerPool(jobs.ProviderWorkerPoolConfig{
		Name:      "openrouter",
		LLMClient: client,
		RPS:       1.0,
	})

	scheduler := jobs.NewScheduler(jobs.SchedulerConfig{})
	scheduler.RegisterPool(pool)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	go scheduler.Start(ctx)

	if err := scheduler.Submit(ctx, agentJob); err != nil {
		t.Fatalf("failed to submit job: %v", err)
	}

	// Wait for completion
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			t.Fatal("test timed out")
		case <-ticker.C:
			if agentJob.Done() {
				goto done
			}
		}
	}
done:

	result := agentJob.Result()
	if result == nil {
		t.Fatal("expected result")
	}

	t.Logf("Result: success=%t iterations=%d error=%s",
		result.Success, result.Iterations, result.Error)

	// Should have failed due to max iterations
	if result.Success {
		t.Error("expected failure due to max iterations")
	}
	if result.Iterations != 3 {
		t.Errorf("expected 3 iterations, got %d", result.Iterations)
	}
}

// TestFileTools_Unit tests FileTools without API calls
func TestFileTools_Unit(t *testing.T) {
	tmpDir := t.TempDir()
	tools := NewFileTools(tmpDir)

	ctx := context.Background()

	// Test list_dir on empty directory
	result, err := tools.ExecuteTool(ctx, "list_dir", map[string]any{"path": "."})
	if err != nil {
		t.Fatalf("list_dir failed: %v", err)
	}
	t.Logf("list_dir result: %s", result)

	// Test write_file
	result, err = tools.ExecuteTool(ctx, "write_file", map[string]any{
		"path":    "test.txt",
		"content": "Hello World",
	})
	if err != nil {
		t.Fatalf("write_file failed: %v", err)
	}
	if !strings.Contains(result, "success") {
		t.Errorf("write_file should succeed, got: %s", result)
	}

	// Test read_file
	result, err = tools.ExecuteTool(ctx, "read_file", map[string]any{"path": "test.txt"})
	if err != nil {
		t.Fatalf("read_file failed: %v", err)
	}
	if !strings.Contains(result, "Hello World") {
		t.Errorf("read_file should return content, got: %s", result)
	}

	// Test path traversal prevention
	result, _ = tools.ExecuteTool(ctx, "read_file", map[string]any{"path": "../../../etc/passwd"})
	if !strings.Contains(result, "error") {
		t.Errorf("should reject path traversal, got: %s", result)
	}

	// Test complete
	if tools.IsComplete() {
		t.Error("should not be complete yet")
	}
	result, _ = tools.ExecuteTool(ctx, "complete", map[string]any{"result": "all done"})
	if !tools.IsComplete() {
		t.Error("should be complete after calling complete tool")
	}
	if tools.GetResult() != "all done" {
		t.Errorf("result should be 'all done', got: %v", tools.GetResult())
	}
}

// TestAgentJob_Unit tests AgentJob without API calls using a mock
func TestAgentJob_Unit(t *testing.T) {
	tools := &mockTools{
		tools: []providers.Tool{
			{
				Type: "function",
				Function: providers.ToolFunction{
					Name:        "done",
					Description: "Signal completion",
				},
			},
		},
	}

	agentJob := NewAgentJobFromConfig(AgentJobConfig{
		ID:    "test",
		Tools: tools,
		InitialMessages: []providers.Message{
			{Role: "user", Content: "test"},
		},
		MaxIterations: 5,
	})

	if agentJob.Type() != "agent" {
		t.Errorf("Type() = %s, want 'agent'", agentJob.Type())
	}

	agentJob.SetRecordID("test-record-id")
	if agentJob.ID() != "test-record-id" {
		t.Errorf("ID() = %s, want 'test-record-id'", agentJob.ID())
	}

	if agentJob.Done() {
		t.Error("should not be done initially")
	}

	status, _ := agentJob.Status(context.Background())
	if status["agent_id"] != "test" {
		t.Errorf("status agent_id = %s, want 'test'", status["agent_id"])
	}
}

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

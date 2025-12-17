package pipeline

import (
	"context"
	"testing"

	"github.com/jackzampolin/shelf/internal/jobs"
)

// mockStageStatus implements StageStatus for testing.
type mockStageStatus struct {
	complete bool
	data     map[string]int
}

func (s *mockStageStatus) IsComplete() bool { return s.complete }
func (s *mockStageStatus) Data() any        { return s.data }

// mockStage implements Stage for testing.
type mockStage struct {
	name                string
	dependencies        []string
	icon                string
	description         string
	requiredCollections []string
}

func newMockStage(name string, deps ...string) *mockStage {
	return &mockStage{
		name:                name,
		dependencies:        deps,
		icon:                "test-icon",
		description:         "test stage",
		requiredCollections: []string{"Book", "Page"},
	}
}

func (m *mockStage) Name() string                  { return m.name }
func (m *mockStage) Dependencies() []string        { return m.dependencies }
func (m *mockStage) Icon() string                  { return m.icon }
func (m *mockStage) Description() string           { return m.description }
func (m *mockStage) RequiredCollections() []string { return m.requiredCollections }

func (m *mockStage) GetStatus(ctx context.Context, bookID string) (StageStatus, error) {
	return &mockStageStatus{complete: false, data: map[string]int{"total": 100, "done": 0}}, nil
}

func (m *mockStage) CreateJob(ctx context.Context, bookID string, opts StageOptions) (jobs.Job, error) {
	return nil, nil
}

func TestRegistry_Register(t *testing.T) {
	r := NewRegistry()

	stage := newMockStage("test-stage")
	if err := r.Register(stage); err != nil {
		t.Fatalf("Register failed: %v", err)
	}

	// Duplicate registration should fail
	if err := r.Register(stage); err == nil {
		t.Fatal("expected error for duplicate registration")
	}
}

func TestRegistry_Get(t *testing.T) {
	r := NewRegistry()

	stage := newMockStage("test-stage")
	r.Register(stage)

	got, ok := r.Get("test-stage")
	if !ok {
		t.Fatal("Get returned false for registered stage")
	}
	if got.Name() != "test-stage" {
		t.Errorf("got name %q, want %q", got.Name(), "test-stage")
	}

	_, ok = r.Get("nonexistent")
	if ok {
		t.Fatal("Get returned true for nonexistent stage")
	}
}

func TestRegistry_List(t *testing.T) {
	r := NewRegistry()

	r.Register(newMockStage("stage-a"))
	r.Register(newMockStage("stage-b"))
	r.Register(newMockStage("stage-c"))

	stages := r.List()
	if len(stages) != 3 {
		t.Fatalf("got %d stages, want 3", len(stages))
	}

	// Should maintain registration order
	names := make([]string, len(stages))
	for i, s := range stages {
		names[i] = s.Name()
	}
	want := []string{"stage-a", "stage-b", "stage-c"}
	for i := range want {
		if names[i] != want[i] {
			t.Errorf("order mismatch at %d: got %q, want %q", i, names[i], want[i])
		}
	}
}

func TestRegistry_Names(t *testing.T) {
	r := NewRegistry()

	r.Register(newMockStage("ocr-pages"))
	r.Register(newMockStage("extract-toc"))

	names := r.Names()
	if len(names) != 2 {
		t.Fatalf("got %d names, want 2", len(names))
	}
	if names[0] != "ocr-pages" || names[1] != "extract-toc" {
		t.Errorf("unexpected names: %v", names)
	}
}

func TestRegistry_GetOrdered(t *testing.T) {
	tests := []struct {
		name      string
		stages    []struct{ name string; deps []string }
		wantOrder []string
		wantErr   bool
	}{
		{
			name: "no dependencies",
			stages: []struct{ name string; deps []string }{
				{"a", nil},
				{"b", nil},
				{"c", nil},
			},
			wantOrder: []string{"a", "b", "c"}, // Original order preserved
			wantErr:   false,
		},
		{
			name: "linear dependencies",
			stages: []struct{ name string; deps []string }{
				{"c", []string{"b"}},
				{"b", []string{"a"}},
				{"a", nil},
			},
			wantOrder: []string{"a", "b", "c"},
			wantErr:   false,
		},
		{
			name: "diamond dependencies",
			stages: []struct{ name string; deps []string }{
				{"d", []string{"b", "c"}},
				{"b", []string{"a"}},
				{"c", []string{"a"}},
				{"a", nil},
			},
			// a must come first, then b and c (either order), then d
			wantOrder: nil, // Just check length since b/c order is undefined
			wantErr:   false,
		},
		{
			name: "cycle detection",
			stages: []struct{ name string; deps []string }{
				{"a", []string{"b"}},
				{"b", []string{"a"}},
			},
			wantErr: true,
		},
		{
			name: "unknown dependency",
			stages: []struct{ name string; deps []string }{
				{"a", []string{"nonexistent"}},
			},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := NewRegistry()
			for _, s := range tt.stages {
				r.Register(newMockStage(s.name, s.deps...))
			}

			ordered, err := r.GetOrdered()
			if tt.wantErr {
				if err == nil {
					t.Fatal("expected error, got nil")
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}

			if tt.wantOrder != nil {
				if len(ordered) != len(tt.wantOrder) {
					t.Fatalf("got %d stages, want %d", len(ordered), len(tt.wantOrder))
				}
				for i, want := range tt.wantOrder {
					if ordered[i].Name() != want {
						t.Errorf("position %d: got %q, want %q", i, ordered[i].Name(), want)
					}
				}
			} else {
				// Just verify count for non-deterministic cases
				if len(ordered) != len(tt.stages) {
					t.Fatalf("got %d stages, want %d", len(ordered), len(tt.stages))
				}
			}
		})
	}
}

func TestRegistry_Validate(t *testing.T) {
	t.Run("valid", func(t *testing.T) {
		r := NewRegistry()
		r.Register(newMockStage("a"))
		r.Register(newMockStage("b", "a"))

		if err := r.Validate(); err != nil {
			t.Fatalf("Validate failed: %v", err)
		}
	})

	t.Run("unknown dependency", func(t *testing.T) {
		r := NewRegistry()
		r.Register(newMockStage("a", "missing"))

		if err := r.Validate(); err == nil {
			t.Fatal("expected error for unknown dependency")
		}
	})
}

func TestRegistry_DependentsOf(t *testing.T) {
	r := NewRegistry()
	r.Register(newMockStage("a"))
	r.Register(newMockStage("b", "a"))
	r.Register(newMockStage("c", "a"))
	r.Register(newMockStage("d", "b"))

	dependents := r.DependentsOf("a")
	if len(dependents) != 2 {
		t.Fatalf("got %d dependents, want 2", len(dependents))
	}

	names := make(map[string]bool)
	for _, s := range dependents {
		names[s.Name()] = true
	}
	if !names["b"] || !names["c"] {
		t.Errorf("expected b and c as dependents, got: %v", names)
	}
}

func TestRegistry_DependenciesOf(t *testing.T) {
	r := NewRegistry()
	r.Register(newMockStage("a"))
	r.Register(newMockStage("b"))
	r.Register(newMockStage("c", "a", "b"))

	deps := r.DependenciesOf("c")
	if len(deps) != 2 {
		t.Fatalf("got %d dependencies, want 2", len(deps))
	}

	names := make(map[string]bool)
	for _, s := range deps {
		names[s.Name()] = true
	}
	if !names["a"] || !names["b"] {
		t.Errorf("expected a and b as dependencies, got: %v", names)
	}

	// Non-existent stage
	deps = r.DependenciesOf("nonexistent")
	if deps != nil {
		t.Errorf("expected nil for nonexistent stage, got: %v", deps)
	}
}

func TestStageStatus_Interface(t *testing.T) {
	// Test that mockStageStatus implements StageStatus
	var status StageStatus = &mockStageStatus{complete: false}

	if status.IsComplete() {
		t.Error("expected IsComplete() to return false")
	}

	status = &mockStageStatus{complete: true, data: map[string]int{"pages": 100}}
	if !status.IsComplete() {
		t.Error("expected IsComplete() to return true")
	}

	data, ok := status.Data().(map[string]int)
	if !ok {
		t.Fatal("expected Data() to return map[string]int")
	}
	if data["pages"] != 100 {
		t.Errorf("unexpected data: %v", data)
	}
}

func TestStage_GetStatus(t *testing.T) {
	stage := newMockStage("test-stage")
	ctx := context.Background()

	status, err := stage.GetStatus(ctx, "book-123")
	if err != nil {
		t.Fatalf("GetStatus failed: %v", err)
	}

	if status.IsComplete() {
		t.Error("expected stage to not be complete")
	}
}

func TestStage_RequiredCollections(t *testing.T) {
	stage := newMockStage("test-stage")

	collections := stage.RequiredCollections()
	if len(collections) != 2 {
		t.Fatalf("expected 2 collections, got %d", len(collections))
	}
	if collections[0] != "Book" || collections[1] != "Page" {
		t.Errorf("unexpected collections: %v", collections)
	}
}

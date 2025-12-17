package pipeline

import (
	"errors"
	"fmt"
	"sync"
)

// Sentinel errors for the pipeline package.
var (
	// ErrStageAlreadyRegistered is returned when registering a duplicate stage.
	ErrStageAlreadyRegistered = errors.New("stage already registered")

	// ErrStageNotFound is returned when a stage dependency is not found.
	ErrStageNotFound = errors.New("stage not found")

	// ErrDependencyCycle is returned when stage dependencies form a cycle.
	ErrDependencyCycle = errors.New("dependency cycle detected")
)

// Registry manages available stages and their dependencies.
type Registry struct {
	mu     sync.RWMutex
	stages map[string]Stage
	order  []string // Maintains registration order
}

// NewRegistry creates an empty stage registry.
func NewRegistry() *Registry {
	return &Registry{
		stages: make(map[string]Stage),
		order:  make([]string, 0),
	}
}

// Register adds a stage to the registry.
// Returns an error if a stage with the same name is already registered.
func (r *Registry) Register(s Stage) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	name := s.Name()
	if _, exists := r.stages[name]; exists {
		return fmt.Errorf("%w: %s", ErrStageAlreadyRegistered, name)
	}

	r.stages[name] = s
	r.order = append(r.order, name)
	return nil
}

// Get returns a stage by name.
func (r *Registry) Get(name string) (Stage, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	s, ok := r.stages[name]
	return s, ok
}

// List returns all stages in registration order.
func (r *Registry) List() []Stage {
	r.mu.RLock()
	defer r.mu.RUnlock()

	stages := make([]Stage, 0, len(r.order))
	for _, name := range r.order {
		stages = append(stages, r.stages[name])
	}
	return stages
}

// Names returns all stage names in registration order.
func (r *Registry) Names() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()

	names := make([]string, len(r.order))
	copy(names, r.order)
	return names
}

// GetOrdered returns stages sorted by dependencies.
// Stages with no dependencies come first, then stages whose
// dependencies are satisfied, etc. When multiple stages have
// the same dependency level, registration order is preserved.
func (r *Registry) GetOrdered() ([]Stage, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	// Build in-degree count using r.order for deterministic iteration
	inDegree := make(map[string]int)
	for _, name := range r.order {
		inDegree[name] = 0
	}

	for _, name := range r.order {
		stage := r.stages[name]
		for _, dep := range stage.Dependencies() {
			if _, ok := r.stages[dep]; !ok {
				return nil, fmt.Errorf("%w: stage %q depends on %q", ErrStageNotFound, name, dep)
			}
			inDegree[name]++
		}
	}

	// Kahn's algorithm for topological sort
	// Use r.order to maintain stable ordering when adding to queue
	var queue []string
	for _, name := range r.order {
		if inDegree[name] == 0 {
			queue = append(queue, name)
		}
	}

	var ordered []Stage
	for len(queue) > 0 {
		// Pop from queue
		name := queue[0]
		queue = queue[1:]

		ordered = append(ordered, r.stages[name])

		// Decrease in-degree for dependents (iterate in registration order)
		for _, depName := range r.order {
			stage := r.stages[depName]
			for _, dep := range stage.Dependencies() {
				if dep == name {
					inDegree[depName]--
					if inDegree[depName] == 0 {
						queue = append(queue, depName)
					}
				}
			}
		}
	}

	// Check for cycles
	if len(ordered) != len(r.stages) {
		return nil, ErrDependencyCycle
	}

	return ordered, nil
}

// Validate checks that all stage dependencies exist in the registry.
func (r *Registry) Validate() error {
	r.mu.RLock()
	defer r.mu.RUnlock()

	for name, stage := range r.stages {
		for _, dep := range stage.Dependencies() {
			if _, ok := r.stages[dep]; !ok {
				return fmt.Errorf("%w: stage %q depends on %q", ErrStageNotFound, name, dep)
			}
		}
	}

	// Also check for cycles
	_, err := r.GetOrdered()
	return err
}

// DependentsOf returns all stages that depend on the given stage.
func (r *Registry) DependentsOf(name string) []Stage {
	r.mu.RLock()
	defer r.mu.RUnlock()

	var dependents []Stage
	for _, stage := range r.stages {
		for _, dep := range stage.Dependencies() {
			if dep == name {
				dependents = append(dependents, stage)
				break
			}
		}
	}
	return dependents
}

// DependenciesOf returns all stages that the given stage depends on.
func (r *Registry) DependenciesOf(name string) []Stage {
	r.mu.RLock()
	defer r.mu.RUnlock()

	stage, ok := r.stages[name]
	if !ok {
		return nil
	}

	var deps []Stage
	for _, depName := range stage.Dependencies() {
		if dep, ok := r.stages[depName]; ok {
			deps = append(deps, dep)
		}
	}
	return deps
}

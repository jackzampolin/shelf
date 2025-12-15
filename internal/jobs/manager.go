package jobs

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
)

// Manager handles job record CRUD operations in DefraDB.
// It does not execute jobs - that's handled by external processors
// that update job status via the manager.
type Manager struct {
	defra  *defra.Client
	logger *slog.Logger
}

// NewManager creates a new job manager.
func NewManager(client *defra.Client, logger *slog.Logger) *Manager {
	if logger == nil {
		logger = slog.Default()
	}
	return &Manager{
		defra:  client,
		logger: logger,
	}
}

// Create creates a new job record in DefraDB.
func (m *Manager) Create(ctx context.Context, jobType string, metadata map[string]any) (string, error) {
	record := NewRecord(jobType, metadata)

	id, err := m.createJob(ctx, record)
	if err != nil {
		return "", fmt.Errorf("failed to create job: %w", err)
	}

	m.logger.Info("job created", "id", id, "type", jobType)
	return id, nil
}

// Get returns a job record by ID.
func (m *Manager) Get(ctx context.Context, jobID string) (*Record, error) {
	return m.getJob(ctx, jobID)
}

// List returns jobs matching the filter.
func (m *Manager) List(ctx context.Context, filter ListFilter) ([]*Record, error) {
	return m.listJobs(ctx, filter)
}

// UpdateStatus updates a job's status.
func (m *Manager) UpdateStatus(ctx context.Context, jobID string, status Status, errMsg string) error {
	return m.updateJobStatus(ctx, jobID, status, errMsg)
}

// UpdateMetadata updates a job's metadata (for progress tracking).
func (m *Manager) UpdateMetadata(ctx context.Context, jobID string, metadata map[string]any) error {
	return m.updateJobMetadata(ctx, jobID, metadata)
}

// ListFilter specifies criteria for listing jobs.
type ListFilter struct {
	Status  Status // Filter by status (empty = all)
	JobType string // Filter by job type (empty = all)
	Limit   int    // Max results (0 = default 100)
}

// DefraDB operations

func (m *Manager) createJob(ctx context.Context, record *Record) (string, error) {
	input := map[string]any{
		"job_type":   record.JobType,
		"status":     string(record.Status),
		"created_at": record.CreatedAt.Format(time.RFC3339),
	}
	if record.Metadata != nil {
		metaJSON, _ := json.Marshal(record.Metadata)
		input["metadata"] = string(metaJSON)
	}

	return m.defra.Create(ctx, "Job", input)
}

func (m *Manager) getJob(ctx context.Context, jobID string) (*Record, error) {
	query := fmt.Sprintf(`{
		Job(docID: %q) {
			_docID
			job_type
			status
			created_at
			started_at
			completed_at
			error
			metadata
		}
	}`, jobID)

	resp, err := m.defra.Query(ctx, query)
	if err != nil {
		return nil, err
	}

	jobs, ok := resp.Data["Job"].([]any)
	if !ok || len(jobs) == 0 {
		return nil, fmt.Errorf("job not found: %s", jobID)
	}

	return parseJobRecord(jobs[0].(map[string]any))
}

func (m *Manager) listJobs(ctx context.Context, filter ListFilter) ([]*Record, error) {
	// Build filter
	filterParts := []string{}
	if filter.Status != "" {
		filterParts = append(filterParts, fmt.Sprintf(`status: {_eq: %q}`, filter.Status))
	}
	if filter.JobType != "" {
		filterParts = append(filterParts, fmt.Sprintf(`job_type: {_eq: %q}`, filter.JobType))
	}

	filterStr := ""
	if len(filterParts) > 0 {
		filterStr = fmt.Sprintf("filter: {%s}", joinParts(filterParts))
	}

	limit := filter.Limit
	if limit <= 0 {
		limit = 100
	}

	query := fmt.Sprintf(`{
		Job(%s, limit: %d) {
			_docID
			job_type
			status
			created_at
			started_at
			completed_at
			error
			metadata
		}
	}`, filterStr, limit)

	resp, err := m.defra.Query(ctx, query)
	if err != nil {
		return nil, err
	}

	jobs, ok := resp.Data["Job"].([]any)
	if !ok {
		return []*Record{}, nil
	}

	records := make([]*Record, 0, len(jobs))
	for _, j := range jobs {
		record, err := parseJobRecord(j.(map[string]any))
		if err != nil {
			continue
		}
		records = append(records, record)
	}

	return records, nil
}

func (m *Manager) updateJobStatus(ctx context.Context, jobID string, status Status, errMsg string) error {
	updates := []string{
		fmt.Sprintf(`status: %q`, status),
	}

	now := time.Now().UTC().Format(time.RFC3339)
	switch status {
	case StatusRunning:
		updates = append(updates, fmt.Sprintf(`started_at: %q`, now))
	case StatusCompleted, StatusFailed, StatusCancelled:
		updates = append(updates, fmt.Sprintf(`completed_at: %q`, now))
	}

	if errMsg != "" {
		updates = append(updates, fmt.Sprintf(`error: %q`, errMsg))
	}

	mutation := fmt.Sprintf(`mutation {
		update_Job(docID: %q, input: {%s}) {
			_docID
		}
	}`, jobID, joinParts(updates))

	_, err := m.defra.Mutation(ctx, mutation, nil)
	return err
}

func (m *Manager) updateJobMetadata(ctx context.Context, jobID string, metadata map[string]any) error {
	metaJSON, err := json.Marshal(metadata)
	if err != nil {
		return fmt.Errorf("failed to marshal metadata: %w", err)
	}

	mutation := fmt.Sprintf(`mutation {
		update_Job(docID: %q, input: {metadata: %q}) {
			_docID
		}
	}`, jobID, string(metaJSON))

	_, err = m.defra.Mutation(ctx, mutation, nil)
	return err
}

// Helper functions

func parseJobRecord(data map[string]any) (*Record, error) {
	record := &Record{}

	if id, ok := data["_docID"].(string); ok {
		record.ID = id
	}
	if jt, ok := data["job_type"].(string); ok {
		record.JobType = jt
	}
	if s, ok := data["status"].(string); ok {
		record.Status = Status(s)
	}
	if e, ok := data["error"].(string); ok {
		record.Error = e
	}

	// Parse timestamps
	if ca, ok := data["created_at"].(string); ok && ca != "" {
		if t, err := time.Parse(time.RFC3339, ca); err == nil {
			record.CreatedAt = t
		}
	}
	if sa, ok := data["started_at"].(string); ok && sa != "" {
		if t, err := time.Parse(time.RFC3339, sa); err == nil {
			record.StartedAt = &t
		}
	}
	if ca, ok := data["completed_at"].(string); ok && ca != "" {
		if t, err := time.Parse(time.RFC3339, ca); err == nil {
			record.CompletedAt = &t
		}
	}

	// Parse metadata
	if meta, ok := data["metadata"].(string); ok && meta != "" {
		var m map[string]any
		if err := json.Unmarshal([]byte(meta), &m); err == nil {
			record.Metadata = m
		}
	}

	return record, nil
}

func joinParts(parts []string) string {
	result := ""
	for i, p := range parts {
		if i > 0 {
			result += ", "
		}
		result += p
	}
	return result
}

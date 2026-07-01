package jobs

import (
	"context"
	"time"
)

// reconcileInterval is how often the scheduler scans for stalled books.
const reconcileInterval = 2 * time.Minute

// bookIsStranded reports whether a book currently in "processing" is stranded:
// it has no active in-memory job, no queued/running job record, and at least
// one failed job record.
func bookIsStranded(hasActiveInMemoryJob bool, records []*Record) bool {
	if hasActiveInMemoryJob {
		return false
	}
	hasFailed := false
	for _, r := range records {
		switch r.Status {
		case StatusRunning, StatusQueued:
			return false
		case StatusFailed:
			hasFailed = true
		}
	}
	return hasFailed
}

// reconcileLoop periodically marks stalled books failed. Flag-only: it never
// resubmits work.
func (s *Scheduler) reconcileLoop(ctx context.Context) {
	ticker := time.NewTicker(reconcileInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			s.reconcileStalledBooks(ctx)
		}
	}
}

// reconcileStalledBooks queries books in "processing", and for any that are
// stranded, marks them "failed" with a reason. Requires a DefraDB-backed job
// manager; a no-op otherwise.
func (s *Scheduler) reconcileStalledBooks(ctx context.Context) {
	if s.manager == nil || s.manager.defra == nil {
		return
	}
	client := s.manager.defra

	resp, err := client.Query(ctx, `{ Book(filter: {status: {_eq: "processing"}}) { _docID } }`)
	if err != nil {
		s.logger.Warn("reconciler: failed to query processing books", "error", err)
		return
	}
	if msg := resp.Error(); msg != "" {
		s.logger.Warn("reconciler: query returned error", "error", msg)
		return
	}

	data, _ := resp.Data["Book"].([]any)
	for _, item := range data {
		m, ok := item.(map[string]any)
		if !ok {
			continue
		}
		docID, _ := m["_docID"].(string)
		if docID == "" {
			continue
		}

		hasActive := s.GetJobByBookID(docID) != nil
		records, err := s.manager.List(ctx, ListFilter{BookID: docID})
		if err != nil {
			s.logger.Warn("reconciler: failed to list jobs for book", "book_id", docID, "error", err)
			continue
		}
		if !bookIsStranded(hasActive, records) {
			continue
		}

		reason := "stalled: processing with no active job and a failed job record (reconciler)"
		if err := client.Update(ctx, "Book", docID, map[string]any{
			"status":        "failed",
			"status_reason": reason,
		}); err != nil {
			s.logger.Warn("reconciler: failed to mark book failed", "book_id", docID, "error", err)
			continue
		}
		s.logger.Info("reconciler marked stalled book failed", "book_id", docID)
	}
}

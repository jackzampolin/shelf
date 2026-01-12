package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
)

// JobCreator is a function that creates a job from a book ID.
// This is the standard signature for book-based job creation.
type JobCreator func(ctx context.Context, bookID string) (jobs.Job, error)

// MakeJobFactory creates a standard job factory from a job creator function.
// All book-based jobs use this pattern:
//  1. Extract book_id from job metadata
//  2. Create the job using the provided creator
//  3. Set the job's record ID
//
// This eliminates the boilerplate JobFactory function that was duplicated
// across all job types.
//
// Usage:
//
//	func JobFactory(cfg Config) jobs.JobFactory {
//	    return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
//	        return NewJob(ctx, cfg, bookID)
//	    })
//	}
func MakeJobFactory(creator JobCreator) jobs.JobFactory {
	return func(ctx context.Context, id string, metadata map[string]any) (jobs.Job, error) {
		bookID, ok := metadata["book_id"].(string)
		if !ok {
			return nil, fmt.Errorf("missing book_id in job metadata")
		}

		job, err := creator(ctx, bookID)
		if err != nil {
			return nil, fmt.Errorf("failed to create job: %w", err)
		}

		job.SetRecordID(id)
		return job, nil
	}
}

package jobs

import (
	"context"
	"log/slog"
	"testing"
	"time"
)

func TestMockJob(t *testing.T) {
	t.Run("executes successfully", func(t *testing.T) {
		job := NewMockJob()
		job.Duration = 50 * time.Millisecond

		ctx := ContextWithDeps(context.Background(), Dependencies{
			Logger: slog.Default(),
		})

		err := job.Execute(ctx)
		if err != nil {
			t.Fatalf("Execute() error = %v", err)
		}

		status, err := job.Status(ctx)
		if err != nil {
			t.Fatalf("Status() error = %v", err)
		}

		if status["step"] != "5" {
			t.Errorf("expected step=5, got %s", status["step"])
		}
	})

	t.Run("respects cancellation", func(t *testing.T) {
		job := NewMockJob()
		job.Duration = 5 * time.Second

		ctx, cancel := context.WithCancel(context.Background())

		done := make(chan error)
		go func() {
			done <- job.Execute(ctx)
		}()

		time.Sleep(50 * time.Millisecond)
		cancel()

		err := <-done
		if err != context.Canceled {
			t.Errorf("expected context.Canceled, got %v", err)
		}
	})

	t.Run("fails when configured", func(t *testing.T) {
		job := NewMockJob()
		job.Duration = 10 * time.Millisecond
		job.ShouldFail = true

		err := job.Execute(context.Background())
		if err == nil {
			t.Error("expected error, got nil")
		}
	})
}

func TestTimerJob(t *testing.T) {
	t.Run("executes for duration", func(t *testing.T) {
		job := NewTimerJob(200 * time.Millisecond)

		ctx := ContextWithDeps(context.Background(), Dependencies{
			Logger: slog.Default(),
		})

		start := time.Now()
		err := job.Execute(ctx)
		elapsed := time.Since(start)

		if err != nil {
			t.Fatalf("Execute() error = %v", err)
		}

		if elapsed < 200*time.Millisecond {
			t.Errorf("completed too fast: %v", elapsed)
		}
		if elapsed > 400*time.Millisecond {
			t.Errorf("took too long: %v", elapsed)
		}

		status, _ := job.Status(ctx)
		if status["done"] != "true" {
			t.Errorf("expected done=true, got %s", status["done"])
		}
		if status["remaining_ms"] != "0" {
			t.Errorf("expected remaining_ms=0, got %s", status["remaining_ms"])
		}
	})

	t.Run("reports remaining time", func(t *testing.T) {
		job := NewTimerJob(500 * time.Millisecond)

		ctx := ContextWithDeps(context.Background(), Dependencies{})

		done := make(chan struct{})
		go func() {
			_ = job.Execute(ctx)
			close(done)
		}()

		// Check status while running
		time.Sleep(100 * time.Millisecond)
		status, _ := job.Status(ctx)

		if status["done"] != "false" {
			t.Errorf("expected done=false while running, got %s", status["done"])
		}

		// Wait for completion
		<-done
	})

	t.Run("respects cancellation", func(t *testing.T) {
		job := NewTimerJob(5 * time.Second)

		ctx, cancel := context.WithCancel(context.Background())

		done := make(chan error)
		go func() {
			done <- job.Execute(ctx)
		}()

		time.Sleep(50 * time.Millisecond)
		cancel()

		err := <-done
		if err != context.Canceled {
			t.Errorf("expected context.Canceled, got %v", err)
		}
	})
}

func TestContextDeps(t *testing.T) {
	t.Run("round trip", func(t *testing.T) {
		logger := slog.Default()
		deps := Dependencies{
			Logger: logger,
		}

		ctx := ContextWithDeps(context.Background(), deps)
		got := DepsFromContext(ctx)

		if got.Logger != logger {
			t.Error("logger not preserved")
		}
	})

	t.Run("missing deps returns empty", func(t *testing.T) {
		deps := DepsFromContext(context.Background())

		if deps.Logger != nil {
			t.Error("expected nil logger")
		}
		if deps.DefraClient != nil {
			t.Error("expected nil DefraClient")
		}
	})
}

func TestNewRecord(t *testing.T) {
	metadata := map[string]any{"key": "value"}
	record := NewRecord("test", metadata)

	if record.JobType != "test" {
		t.Errorf("JobType = %s, want test", record.JobType)
	}
	if record.Status != StatusQueued {
		t.Errorf("Status = %s, want queued", record.Status)
	}
	if record.CreatedAt.IsZero() {
		t.Error("CreatedAt is zero")
	}
	if record.Metadata["key"] != "value" {
		t.Error("metadata not preserved")
	}
}

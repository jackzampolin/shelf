package defra

import (
	"context"
	"testing"
)

func TestSinkParentCancellationDoesNotPreemptStopFlush(t *testing.T) {
	parent, cancel := context.WithCancel(context.Background())
	sink := NewSink(SinkConfig{})
	sink.Start(parent)
	cancel()
	if err := sink.ctx.Err(); err != nil {
		t.Fatalf("sink context canceled before Stop: %v", err)
	}
	sink.Stop()
	if err := sink.ctx.Err(); err != context.Canceled {
		t.Fatalf("sink context after Stop = %v, want context.Canceled", err)
	}
}

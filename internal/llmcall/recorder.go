package llmcall

import (
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/providers"
)

// Recorder handles fire-and-forget LLM call recording via a Sink.
type Recorder struct {
	sink *defra.Sink
}

// NewRecorder creates a new LLM call recorder.
func NewRecorder(sink *defra.Sink) *Recorder {
	return &Recorder{sink: sink}
}

// Record captures an LLM call asynchronously.
// This is non-blocking - the write is queued and batched.
func (r *Recorder) Record(result *providers.ChatResult, opts RecordOptions) {
	if r.sink == nil {
		return // No sink configured, skip recording
	}

	call := FromChatResult(result, opts)
	r.sink.Send(defra.WriteOp{
		Op:         defra.OpCreate,
		Collection: "LLMCall",
		Document:   call.ToMap(),
	})
}

// RecordCall captures an already-constructed Call asynchronously.
func (r *Recorder) RecordCall(call *Call) {
	if r.sink == nil || call == nil {
		return
	}

	r.sink.Send(defra.WriteOp{
		Op:         defra.OpCreate,
		Collection: "LLMCall",
		Document:   call.ToMap(),
	})
}

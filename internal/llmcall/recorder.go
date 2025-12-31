package llmcall

import (
	"log/slog"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/providers"
)

// Recorder handles fire-and-forget LLM call recording via a Sink.
// Use Recorder for writing (during LLM calls) and Store for reading (querying history).
type Recorder struct {
	sink   *defra.Sink
	logger *slog.Logger
}

// NewRecorder creates a new LLM call recorder.
// If sink is nil, calls will be logged as warnings but not recorded.
func NewRecorder(sink *defra.Sink, logger *slog.Logger) *Recorder {
	if logger == nil {
		logger = slog.Default()
	}
	return &Recorder{sink: sink, logger: logger}
}

// Record captures an LLM call asynchronously.
// The write is queued for batched processing. This may block briefly if the
// internal queue is full, but will not wait for the write to complete.
func (r *Recorder) Record(result *providers.ChatResult, opts RecordOptions) {
	if r.sink == nil {
		r.logger.Warn("LLM call not recorded: sink not configured (check server initialization)",
			"prompt_key", opts.PromptKey,
			"book_id", opts.BookID,
			"job_id", opts.JobID)
		return
	}

	call := FromChatResult(result, opts)
	if call == nil {
		r.logger.Warn("LLM call not recorded: nil result provided",
			"prompt_key", opts.PromptKey)
		return
	}

	r.sink.Send(defra.WriteOp{
		Op:         defra.OpCreate,
		Collection: "LLMCall",
		Document:   call.ToMap(),
	})
}

// RecordCall captures an already-constructed Call asynchronously.
func (r *Recorder) RecordCall(call *Call) {
	if r.sink == nil {
		r.logger.Warn("LLM call not recorded: sink not configured",
			"call_id", call.ID)
		return
	}
	if call == nil {
		r.logger.Warn("LLM call not recorded: nil call provided")
		return
	}

	r.sink.Send(defra.WriteOp{
		Op:         defra.OpCreate,
		Collection: "LLMCall",
		Document:   call.ToMap(),
	})
}

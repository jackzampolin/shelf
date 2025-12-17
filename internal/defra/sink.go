package defra

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
	"time"
)

// OpType represents the type of write operation.
type OpType string

const (
	OpCreate OpType = "create"
	OpUpdate OpType = "update"
	OpDelete OpType = "delete"
)

// WriteOp represents a single write operation to be batched.
type WriteOp struct {
	Collection string         // Target collection name
	Document   map[string]any // Document data
	DocID      string         // For updates/deletes (empty for creates)
	Op         OpType         // Operation type
	result     chan<- WriteResult // Internal - set by SendSync
}

// WriteResult contains the result of a write operation.
type WriteResult struct {
	DocID string // Stable document ID
	Err   error  // Error if operation failed
}

// SinkConfig configures the write sink.
type SinkConfig struct {
	Client        *Client
	BatchSize     int           // Flush after N ops (default: 100)
	FlushInterval time.Duration // Or after duration (default: 5s)
	Concurrency   int           // Number of concurrent workers (default: 4)
	QueueSize     int           // Buffer size (default: 1000)
	Logger        *slog.Logger
}

// Sink batches and coordinates writes to DefraDB.
type Sink struct {
	client *Client
	logger *slog.Logger

	// Configuration
	batchSize     int
	flushInterval time.Duration
	concurrency   int

	// Internal state
	queue    chan WriteOp
	batch    []WriteOp
	batchMu  sync.Mutex
	flushCh  chan struct{} // Signal to flush immediately

	// Lifecycle
	ctx      context.Context
	cancel   context.CancelFunc
	wg       sync.WaitGroup
	stopOnce sync.Once
}

// NewSink creates a new write sink.
func NewSink(cfg SinkConfig) *Sink {
	// Apply defaults
	if cfg.BatchSize <= 0 {
		cfg.BatchSize = 100
	}
	if cfg.FlushInterval <= 0 {
		cfg.FlushInterval = 5 * time.Second
	}
	if cfg.Concurrency <= 0 {
		cfg.Concurrency = 4
	}
	if cfg.QueueSize <= 0 {
		cfg.QueueSize = 1000
	}
	if cfg.Logger == nil {
		cfg.Logger = slog.Default()
	}

	return &Sink{
		client:        cfg.Client,
		logger:        cfg.Logger,
		batchSize:     cfg.BatchSize,
		flushInterval: cfg.FlushInterval,
		concurrency:   cfg.Concurrency,
		queue:         make(chan WriteOp, cfg.QueueSize),
		batch:         make([]WriteOp, 0, cfg.BatchSize),
		flushCh:       make(chan struct{}, 1),
	}
}

// Start begins processing write operations.
func (s *Sink) Start(ctx context.Context) {
	s.ctx, s.cancel = context.WithCancel(ctx)

	// Start the batcher goroutine
	s.wg.Add(1)
	go s.runBatcher()
}

// Stop gracefully shuts down the sink, flushing remaining operations.
func (s *Sink) Stop() {
	s.stopOnce.Do(func() {
		s.logger.Info("stopping sink, flushing remaining operations")

		// Close queue to stop accepting new ops and signal shutdown
		close(s.queue)

		// Wait for batcher to finish (it will flush remaining)
		s.wg.Wait()

		// Now cancel context
		s.cancel()

		s.logger.Info("sink stopped")
	})
}

// Send queues a write operation (fire-and-forget).
// Returns immediately without waiting for the write to complete.
func (s *Sink) Send(op WriteOp) {
	op.result = nil // Ensure fire-and-forget

	// Use recover to handle send on closed channel
	defer func() {
		if r := recover(); r != nil {
			s.logger.Warn("sink closed, dropping write op",
				"collection", op.Collection,
				"op", op.Op)
		}
	}()

	select {
	case s.queue <- op:
	default:
		// Queue full, try with context check
		select {
		case s.queue <- op:
		case <-s.ctx.Done():
			s.logger.Warn("sink closed, dropping write op",
				"collection", op.Collection,
				"op", op.Op)
		}
	}
}

// SendSync queues a write operation and waits for the result.
// Returns the document ID on success.
func (s *Sink) SendSync(ctx context.Context, op WriteOp) (WriteResult, error) {
	resultCh := make(chan WriteResult, 1)
	op.result = resultCh

	select {
	case s.queue <- op:
	case <-s.ctx.Done():
		return WriteResult{}, fmt.Errorf("sink closed")
	case <-ctx.Done():
		return WriteResult{}, ctx.Err()
	}

	// Wait for result
	select {
	case result := <-resultCh:
		return result, result.Err
	case <-s.ctx.Done():
		return WriteResult{}, fmt.Errorf("sink closed while waiting for result")
	case <-ctx.Done():
		return WriteResult{}, ctx.Err()
	}
}

// Flush forces an immediate flush of the current batch.
func (s *Sink) Flush(ctx context.Context) error {
	select {
	case s.flushCh <- struct{}{}:
	default:
		// Flush already pending
	}
	return nil
}

// runBatcher collects operations and flushes on size/time triggers.
func (s *Sink) runBatcher() {
	defer s.wg.Done()

	ticker := time.NewTicker(s.flushInterval)
	defer ticker.Stop()

	for {
		select {
		case op, ok := <-s.queue:
			if !ok {
				// Queue closed, flush remaining and exit
				s.flushBatch()
				return
			}
			s.addToBatch(op)

		case <-ticker.C:
			s.flushBatch()

		case <-s.flushCh:
			s.flushBatch()
		}
	}
}

// addToBatch adds an operation to the current batch, flushing if full.
func (s *Sink) addToBatch(op WriteOp) {
	s.batchMu.Lock()
	s.batch = append(s.batch, op)
	shouldFlush := len(s.batch) >= s.batchSize
	s.batchMu.Unlock()

	if shouldFlush {
		s.flushBatch()
	}
}

// flushBatch processes the current batch of operations.
func (s *Sink) flushBatch() {
	s.batchMu.Lock()
	if len(s.batch) == 0 {
		s.batchMu.Unlock()
		return
	}
	ops := s.batch
	s.batch = make([]WriteOp, 0, s.batchSize)
	s.batchMu.Unlock()

	s.logger.Debug("flushing batch", "count", len(ops))

	// Group operations by collection and type
	grouped := s.groupOps(ops)

	// Process each group
	for key, groupOps := range grouped {
		s.processGroup(key.collection, key.op, groupOps)
	}
}

type groupKey struct {
	collection string
	op         OpType
}

// groupOps groups operations by collection and operation type.
func (s *Sink) groupOps(ops []WriteOp) map[groupKey][]WriteOp {
	grouped := make(map[groupKey][]WriteOp)
	for _, op := range ops {
		key := groupKey{collection: op.Collection, op: op.Op}
		grouped[key] = append(grouped[key], op)
	}
	return grouped
}

// processGroup handles a group of same-collection, same-type operations.
func (s *Sink) processGroup(collection string, opType OpType, ops []WriteOp) {
	switch opType {
	case OpCreate:
		s.processCreates(collection, ops)
	case OpUpdate:
		s.processUpdates(collection, ops)
	case OpDelete:
		s.processDeletes(collection, ops)
	}
}

// processCreates handles batched create operations.
func (s *Sink) processCreates(collection string, ops []WriteOp) {
	// For now, process creates individually since DefraDB GraphQL
	// doesn't have a native CreateMany in the HTTP API.
	// TODO: When DefraDB adds batch support, use it here.
	for _, op := range ops {
		docID, err := s.client.Create(s.ctx, collection, op.Document)
		result := WriteResult{DocID: docID, Err: err}

		if err != nil {
			s.logger.Error("create failed",
				"collection", collection,
				"error", err)
		}

		// Send result if caller is waiting
		if op.result != nil {
			op.result <- result
			close(op.result)
		}
	}
}

// processUpdates handles batched update operations.
func (s *Sink) processUpdates(collection string, ops []WriteOp) {
	for _, op := range ops {
		err := s.client.Update(s.ctx, collection, op.DocID, op.Document)
		result := WriteResult{DocID: op.DocID, Err: err}

		if err != nil {
			s.logger.Error("update failed",
				"collection", collection,
				"docID", op.DocID,
				"error", err)
		}

		if op.result != nil {
			op.result <- result
			close(op.result)
		}
	}
}

// processDeletes handles batched delete operations.
func (s *Sink) processDeletes(collection string, ops []WriteOp) {
	for _, op := range ops {
		err := s.client.Delete(s.ctx, collection, op.DocID)
		result := WriteResult{DocID: op.DocID, Err: err}

		if err != nil {
			s.logger.Error("delete failed",
				"collection", collection,
				"docID", op.DocID,
				"error", err)
		}

		if op.result != nil {
			op.result <- result
			close(op.result)
		}
	}
}

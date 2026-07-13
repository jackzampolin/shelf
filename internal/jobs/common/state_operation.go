package common

import (
	"fmt"
)

// OpStatus represents the status of a book-level operation.
type OpStatus int

const (
	OpNotStarted OpStatus = iota
	OpInProgress
	OpComplete
	OpFailed
)

// String returns the string representation of the status.
func (s OpStatus) String() string {
	switch s {
	case OpNotStarted:
		return "not_started"
	case OpInProgress:
		return "in_progress"
	case OpComplete:
		return "complete"
	case OpFailed:
		return "failed"
	default:
		return "unknown"
	}
}

// OperationState tracks the state of a retriable book-level operation.
// Fields are unexported; use the provided methods for all access.
type OperationState struct {
	status  OpStatus
	retries int
}

// NewOperationState creates an OperationState with given status and retries.
// Used for loading state from database.
func NewOperationState(status OpStatus, retries int) OperationState {
	return OperationState{status: status, retries: retries}
}

// Start marks the operation as in progress. Returns error if already started.
func (o *OperationState) Start() error {
	if o.status != OpNotStarted {
		return fmt.Errorf("operation already %s", o.status)
	}
	o.status = OpInProgress
	return nil
}

// Complete marks the operation as successfully completed.
func (o *OperationState) Complete() {
	o.status = OpComplete
}

// Fail records a failure and returns true if permanently failed (max retries reached).
func (o *OperationState) Fail(maxRetries int) bool {
	o.retries++
	if o.retries >= maxRetries {
		o.status = OpFailed
		return true
	}
	o.status = OpNotStarted // Allow retry
	return false
}

// Reset resets the operation to not started state (for rollback on persist failure).
func (o *OperationState) Reset() {
	o.status = OpNotStarted
}

// IsStarted returns true if the operation has been started.
func (o *OperationState) IsStarted() bool {
	return o.status == OpInProgress
}

// IsDone returns true if the operation is complete or permanently failed.
func (o *OperationState) IsDone() bool {
	return o.status == OpComplete || o.status == OpFailed
}

// IsFailed returns true if the operation permanently failed.
func (o *OperationState) IsFailed() bool {
	return o.status == OpFailed
}

// IsComplete returns true if the operation completed successfully.
func (o *OperationState) IsComplete() bool {
	return o.status == OpComplete
}

// CanStart returns true if the operation can be started (not started, not done).
func (o *OperationState) CanStart() bool {
	return o.status == OpNotStarted
}

// GetRetries returns the current retry count.
func (o *OperationState) GetRetries() int {
	return o.retries
}

// Retries returns the current retry count (value receiver for convenience).
func (o OperationState) Retries() int {
	return o.retries
}

// --- Operation State Accessors ---
// Deprecated: These wrapper methods delegate to the generic Op* methods.
// New code should use OpStart(OpMetadata), OpComplete(OpMetadata), etc.

func (b *BookState) MetadataStart() error             { return b.OpStart(OpMetadata) }
func (b *BookState) MetadataComplete()                { b.OpComplete(OpMetadata) }
func (b *BookState) MetadataFail(maxRetries int) bool { return b.OpFail(OpMetadata, maxRetries) }
func (b *BookState) MetadataReset()                   { b.OpReset(OpMetadata) }
func (b *BookState) MetadataIsStarted() bool          { return b.OpIsStarted(OpMetadata) }
func (b *BookState) MetadataIsDone() bool             { return b.OpIsDone(OpMetadata) }
func (b *BookState) MetadataCanStart() bool           { return b.OpCanStart(OpMetadata) }
func (b *BookState) MetadataIsComplete() bool         { return b.OpIsComplete(OpMetadata) }
func (b *BookState) GetMetadataState() OperationState { return b.OpGetState(OpMetadata) }

func (b *BookState) TocFinderStart() error             { return b.OpStart(OpTocFinder) }
func (b *BookState) TocFinderComplete()                { b.OpComplete(OpTocFinder) }
func (b *BookState) TocFinderFail(maxRetries int) bool { return b.OpFail(OpTocFinder, maxRetries) }
func (b *BookState) TocFinderReset()                   { b.OpReset(OpTocFinder) }
func (b *BookState) TocFinderIsStarted() bool          { return b.OpIsStarted(OpTocFinder) }
func (b *BookState) TocFinderIsDone() bool             { return b.OpIsDone(OpTocFinder) }
func (b *BookState) TocFinderCanStart() bool           { return b.OpCanStart(OpTocFinder) }
func (b *BookState) TocFinderIsComplete() bool         { return b.OpIsComplete(OpTocFinder) }
func (b *BookState) GetTocFinderState() OperationState { return b.OpGetState(OpTocFinder) }

func (b *BookState) TocExtractStart() error             { return b.OpStart(OpTocExtract) }
func (b *BookState) TocExtractComplete()                { b.OpComplete(OpTocExtract) }
func (b *BookState) TocExtractFail(maxRetries int) bool { return b.OpFail(OpTocExtract, maxRetries) }
func (b *BookState) TocExtractReset()                   { b.OpReset(OpTocExtract) }
func (b *BookState) TocExtractIsStarted() bool          { return b.OpIsStarted(OpTocExtract) }
func (b *BookState) TocExtractIsDone() bool             { return b.OpIsDone(OpTocExtract) }
func (b *BookState) TocExtractCanStart() bool           { return b.OpCanStart(OpTocExtract) }
func (b *BookState) TocExtractIsComplete() bool         { return b.OpIsComplete(OpTocExtract) }
func (b *BookState) GetTocExtractState() OperationState { return b.OpGetState(OpTocExtract) }

func (b *BookState) TocLinkStart() error             { return b.OpStart(OpTocLink) }
func (b *BookState) TocLinkComplete()                { b.OpComplete(OpTocLink) }
func (b *BookState) TocLinkFail(maxRetries int) bool { return b.OpFail(OpTocLink, maxRetries) }
func (b *BookState) TocLinkReset()                   { b.OpReset(OpTocLink) }
func (b *BookState) TocLinkIsStarted() bool          { return b.OpIsStarted(OpTocLink) }
func (b *BookState) TocLinkIsDone() bool             { return b.OpIsDone(OpTocLink) }
func (b *BookState) TocLinkCanStart() bool           { return b.OpCanStart(OpTocLink) }
func (b *BookState) TocLinkIsComplete() bool         { return b.OpIsComplete(OpTocLink) }
func (b *BookState) GetTocLinkState() OperationState { return b.OpGetState(OpTocLink) }

func (b *BookState) TocFinalizeStart() error             { return b.OpStart(OpTocFinalize) }
func (b *BookState) TocFinalizeComplete()                { b.OpComplete(OpTocFinalize) }
func (b *BookState) TocFinalizeFail(maxRetries int) bool { return b.OpFail(OpTocFinalize, maxRetries) }
func (b *BookState) TocFinalizeReset()                   { b.OpReset(OpTocFinalize) }
func (b *BookState) TocFinalizeIsStarted() bool          { return b.OpIsStarted(OpTocFinalize) }
func (b *BookState) TocFinalizeIsDone() bool             { return b.OpIsDone(OpTocFinalize) }
func (b *BookState) TocFinalizeCanStart() bool           { return b.OpCanStart(OpTocFinalize) }
func (b *BookState) TocFinalizeIsComplete() bool         { return b.OpIsComplete(OpTocFinalize) }
func (b *BookState) GetTocFinalizeState() OperationState { return b.OpGetState(OpTocFinalize) }

func (b *BookState) StructureStart() error             { return b.OpStart(OpStructure) }
func (b *BookState) StructureComplete()                { b.OpComplete(OpStructure) }
func (b *BookState) StructureFail(maxRetries int) bool { return b.OpFail(OpStructure, maxRetries) }
func (b *BookState) StructureReset()                   { b.OpReset(OpStructure) }
func (b *BookState) StructureIsStarted() bool          { return b.OpIsStarted(OpStructure) }
func (b *BookState) StructureIsDone() bool             { return b.OpIsDone(OpStructure) }
func (b *BookState) StructureCanStart() bool           { return b.OpCanStart(OpStructure) }
func (b *BookState) StructureIsComplete() bool         { return b.OpIsComplete(OpStructure) }
func (b *BookState) GetStructureState() OperationState { return b.OpGetState(OpStructure) }

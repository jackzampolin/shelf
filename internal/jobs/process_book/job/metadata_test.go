package job

import "testing"

func TestJobMetadataPreservesPipelineVariant(t *testing.T) {
	job := &Job{PipelineVariant: "ocr-only"}
	metadata := job.JobMetadata()
	if got := metadata["variant"]; got != "ocr-only" {
		t.Fatalf("variant metadata = %v, want ocr-only", got)
	}
}

package process_book

import "testing"

func TestStatusIsCompleteForDirectStructuredImport(t *testing.T) {
	status := &Status{
		TotalPages: 13, OcrComplete: 13, MetadataComplete: true,
		BookComplete: true, StructureComplete: true,
	}
	if !status.IsComplete() {
		t.Fatal("terminal direct import should be complete without scan ToC stages")
	}
}

func TestStatusDirectImportStillRequiresSourceUnits(t *testing.T) {
	status := &Status{
		TotalPages: 13, OcrComplete: 12, MetadataComplete: true,
		BookComplete: true, StructureComplete: true,
	}
	if status.IsComplete() {
		t.Fatal("direct import with a missing source unit should not be complete")
	}
}

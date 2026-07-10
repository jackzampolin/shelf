package endpoints

import (
	"fmt"
	"reflect"
	"testing"

	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/jobs/process_book"
)

func TestParsePageSpec(t *testing.T) {
	pages, err := parsePageSpec("9, 17,19,21,26-28,27")
	if err != nil {
		t.Fatal(err)
	}
	if got := fmt.Sprint(pages); got != "[9 17 19 21 26 27 28]" {
		t.Fatalf("pages = %s", got)
	}

	for _, spec := range []string{"", "0", "3-1", "1-2-3", "abc"} {
		if _, err := parsePageSpec(spec); err == nil {
			t.Errorf("parsePageSpec(%q) error = nil", spec)
		}
	}
}

func TestValidateRepairProviders(t *testing.T) {
	configured := []string{"chandra", "mistral"}
	if err := validateRepairProviders([]string{"chandra"}, configured); err != nil {
		t.Fatal(err)
	}
	if err := validateRepairProviders([]string{"typo"}, configured); err == nil {
		t.Fatal("unconfigured provider error = nil")
	}
}

func standardRepairConfig() process_book.Config {
	return process_book.Config{
		EnableMetadata:    true,
		EnableTocFinder:   true,
		EnableTocExtract:  true,
		EnableTocLink:     true,
		EnableTocFinalize: true,
		EnableStructure:   true,
	}
}

func TestRepairInvalidationPlanPreservesUnaffectedResearchArtifacts(t *testing.T) {
	tests := []struct {
		name  string
		cfg   process_book.Config
		pages []int
		want  []common.ResetOperation
	}{
		{
			name:  "body page keeps metadata and extracted ToC",
			cfg:   standardRepairConfig(),
			pages: []int{592},
			want:  []common.ResetOperation{common.ResetTocLink},
		},
		{
			name:  "front matter page reruns metadata and ToC discovery",
			cfg:   standardRepairConfig(),
			pages: []int{12},
			want:  []common.ResetOperation{common.ResetMetadata, common.ResetTocFinder},
		},
		{
			name:  "late front matter leaves metadata intact",
			cfg:   standardRepairConfig(),
			pages: []int{40},
			want:  []common.ResetOperation{common.ResetTocFinder},
		},
		{
			name: "text only body page has no dependent operation",
			cfg: process_book.Config{
				EnableMetadata: true,
			},
			pages: []int{80},
			want:  nil,
		},
		{
			name: "structure only reruns structure",
			cfg: process_book.Config{
				EnableStructure: true,
			},
			pages: []int{80},
			want:  []common.ResetOperation{common.ResetStructure},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := repairInvalidationPlan(tt.cfg, tt.pages); !reflect.DeepEqual(got, tt.want) {
				t.Fatalf("repairInvalidationPlan() = %v, want %v", got, tt.want)
			}
		})
	}
}

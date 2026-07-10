package endpoints

import (
	"fmt"
	"testing"
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

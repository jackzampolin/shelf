package tools

import (
	"strings"
	"testing"
)

// See toc_entry_finder: anyOf unions make vLLM auto tool-calling emit a
// parseable tool call only intermittently. The result tool must avoid anyOf;
// "not found" is expressed by omitting the optional toc_page_range field.
func TestWriteTocResultTool_NoAnyOfUnion(t *testing.T) {
	params := string(writeTocResultTool().Function.Parameters)
	if strings.Contains(params, "anyOf") {
		t.Errorf("write_toc_result schema uses an anyOf union (breaks vLLM auto tool-calling): %s", params)
	}
}

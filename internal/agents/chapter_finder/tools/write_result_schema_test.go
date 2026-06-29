package tools

import (
	"strings"
	"testing"
)

// See toc_entry_finder: anyOf unions make vLLM auto tool-calling emit a
// parseable tool call only intermittently. The result tool must avoid anyOf;
// "not found" is expressed by omitting the optional scan_page field.
func TestWriteResultTool_NoAnyOfUnion(t *testing.T) {
	params := string(writeResultTool().Function.Parameters)
	if strings.Contains(params, "anyOf") {
		t.Errorf("write_result schema uses an anyOf union (breaks vLLM auto tool-calling): %s", params)
	}
}

package tools

import (
	"strings"
	"testing"
)

// vLLM's tool-calling under the default "auto" choice emits a parseable tool
// call only ~half the time when a parameter schema contains an anyOf union
// (e.g. {integer|null}). That intermittent miss leaves the agent with no tool
// call, triggering the loop's "continue" nudge until it times out (~50% of
// link entries failed this way). "Not found" must be expressed by OMITTING the
// optional scan_page field, not via an anyOf-null union.
func TestWriteResultTool_NoAnyOfUnion(t *testing.T) {
	params := string(writeResultTool().Function.Parameters)
	if strings.Contains(params, "anyOf") {
		t.Errorf("write_result schema uses an anyOf union (breaks vLLM auto tool-calling): %s", params)
	}
}

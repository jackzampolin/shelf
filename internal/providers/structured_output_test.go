package providers

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestSanitizeStructuredSchemaForModel_AnthropicRemovesIntegerBounds(t *testing.T) {
	raw := json.RawMessage(`{
		"name":"test_schema",
		"strict":true,
		"schema":{
			"type":"object",
			"properties":{
				"level":{"type":"integer","minimum":1,"maximum":3},
				"confidence":{"type":"number","minimum":0.0,"maximum":1.0}
			},
			"required":["level"]
		}
	}`)

	got, err := sanitizeStructuredSchemaForModel("anthropic/claude-opus-4.6", raw)
	if err != nil {
		t.Fatalf("sanitizeStructuredSchemaForModel() error = %v", err)
	}

	if strings.Contains(string(got), `"minimum":1`) || strings.Contains(string(got), `"maximum":3`) {
		t.Fatalf("integer minimum/maximum should be removed, got: %s", string(got))
	}
	if !strings.Contains(string(got), `"minimum":0`) && !strings.Contains(string(got), `"minimum":0.0`) {
		t.Fatalf("number minimum should remain, got: %s", string(got))
	}
}

func TestSanitizeStructuredSchemaForModel_NonAnthropicUnchanged(t *testing.T) {
	raw := json.RawMessage(`{"schema":{"type":"object","properties":{"x":{"type":"integer","minimum":1}}}}`)
	got, err := sanitizeStructuredSchemaForModel("openai/gpt-4.1", raw)
	if err != nil {
		t.Fatalf("sanitizeStructuredSchemaForModel() error = %v", err)
	}
	if string(got) != string(raw) {
		t.Fatalf("non-anthropic schema should be unchanged, got: %s", string(got))
	}
}

func TestParseStructuredJSON_StripsCodeFence(t *testing.T) {
	content := "```json\n{\"ok\":true}\n```"
	got, err := parseStructuredJSON(content)
	if err != nil {
		t.Fatalf("parseStructuredJSON() error = %v", err)
	}

	var parsed map[string]any
	if err := json.Unmarshal(got, &parsed); err != nil {
		t.Fatalf("failed to unmarshal parsed JSON: %v", err)
	}
	if ok, _ := parsed["ok"].(bool); !ok {
		t.Fatalf("expected ok=true, got %#v", parsed)
	}
}

func TestValidateStructuredJSON_EnforcesCanonicalBounds(t *testing.T) {
	schema := json.RawMessage(`{
		"name":"toc_extraction",
		"strict":true,
		"schema":{
			"type":"object",
			"properties":{
				"level":{"type":"integer","minimum":1,"maximum":3}
			},
			"required":["level"],
			"additionalProperties":false
		}
	}`)

	valid := json.RawMessage(`{"level":2}`)
	if err := validateStructuredJSON(schema, valid); err != nil {
		t.Fatalf("validateStructuredJSON(valid) error = %v", err)
	}

	invalid := json.RawMessage(`{"level":5}`)
	if err := validateStructuredJSON(schema, invalid); err == nil {
		t.Fatal("validateStructuredJSON(invalid) expected error, got nil")
	}
}

package providers

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/santhosh-tekuri/jsonschema/v5"
)

// maxStructuredRepairAttempts limits provider-side self-repair loops when
// structured output parsing/validation fails.
const maxStructuredRepairAttempts = 2

// adaptedResponseFormat returns a provider-compatible response format while
// preserving the original canonical schema for local validation.
func adaptedResponseFormat(model string, rf *ResponseFormat) (*openRouterResponseFormat, error) {
	if rf == nil {
		return nil, nil
	}
	// OpenRouter may route anthropic/* models to non-Anthropic backends (e.g. Google),
	// where Anthropic beta headers used for native structured outputs are rejected.
	// Use prompt + local validation/repair for anthropic models instead.
	if isAnthropicModel(model) {
		return nil, nil
	}

	adaptedSchema := rf.JSONSchema
	if len(adaptedSchema) > 0 {
		var err error
		adaptedSchema, err = sanitizeStructuredSchemaForModel(model, adaptedSchema)
		if err != nil {
			return nil, err
		}
	}

	return &openRouterResponseFormat{
		Type:       rf.Type,
		JSONSchema: adaptedSchema,
	}, nil
}

// sanitizeStructuredSchemaForModel applies provider/model-specific schema
// compatibility shims. Current: Anthropic via OpenRouter rejects integer
// minimum/maximum bounds in output schemas.
func sanitizeStructuredSchemaForModel(model string, schemaRaw json.RawMessage) (json.RawMessage, error) {
	if len(schemaRaw) == 0 {
		return schemaRaw, nil
	}
	if !isAnthropicModel(model) {
		return schemaRaw, nil
	}

	var root any
	if err := json.Unmarshal(schemaRaw, &root); err != nil {
		return nil, fmt.Errorf("failed to parse structured schema: %w", err)
	}

	stripIntegerBounds(root)

	sanitized, err := json.Marshal(root)
	if err != nil {
		return nil, fmt.Errorf("failed to serialize sanitized structured schema: %w", err)
	}
	return sanitized, nil
}

func isAnthropicModel(model string) bool {
	return strings.HasPrefix(strings.ToLower(strings.TrimSpace(model)), "anthropic/")
}

func stripIntegerBounds(node any) {
	switch n := node.(type) {
	case map[string]any:
		if schemaTypeIncludesInteger(n["type"]) {
			delete(n, "minimum")
			delete(n, "maximum")
			delete(n, "exclusiveMinimum")
			delete(n, "exclusiveMaximum")
		}
		for _, v := range n {
			stripIntegerBounds(v)
		}
	case []any:
		for _, v := range n {
			stripIntegerBounds(v)
		}
	}
}

func schemaTypeIncludesInteger(typeVal any) bool {
	switch t := typeVal.(type) {
	case string:
		return t == "integer"
	case []any:
		for _, item := range t {
			if s, ok := item.(string); ok && s == "integer" {
				return true
			}
		}
	}
	return false
}

// parseStructuredJSON parses JSON from model output, with lightweight recovery
// for markdown code fences and surrounding text.
func parseStructuredJSON(content string) (json.RawMessage, error) {
	content = strings.TrimSpace(content)
	if content == "" {
		return nil, fmt.Errorf("empty structured output")
	}

	candidates := []string{content}
	if stripped := stripCodeFences(content); stripped != "" && stripped != content {
		candidates = append(candidates, stripped)
	}
	if extracted := extractJSONCandidate(content); extracted != "" && extracted != content {
		candidates = append(candidates, extracted)
	}

	seen := make(map[string]struct{}, len(candidates))
	for _, candidate := range candidates {
		candidate = strings.TrimSpace(candidate)
		if candidate == "" {
			continue
		}
		if _, ok := seen[candidate]; ok {
			continue
		}
		seen[candidate] = struct{}{}

		var parsed any
		if err := json.Unmarshal([]byte(candidate), &parsed); err == nil {
			normalized, mErr := json.Marshal(parsed)
			if mErr != nil {
				return nil, fmt.Errorf("failed to normalize structured output: %w", mErr)
			}
			return normalized, nil
		}
	}

	return nil, fmt.Errorf("failed to parse structured JSON")
}

func stripCodeFences(content string) string {
	trimmed := strings.TrimSpace(content)
	if !strings.HasPrefix(trimmed, "```") {
		return ""
	}

	lines := strings.Split(trimmed, "\n")
	if len(lines) < 2 {
		return ""
	}

	// Drop first fence line.
	lines = lines[1:]
	// Drop trailing fence if present.
	if len(lines) > 0 && strings.TrimSpace(lines[len(lines)-1]) == "```" {
		lines = lines[:len(lines)-1]
	}
	return strings.TrimSpace(strings.Join(lines, "\n"))
}

func extractJSONCandidate(content string) string {
	trimmed := strings.TrimSpace(content)
	if trimmed == "" {
		return ""
	}

	objectStart := strings.Index(trimmed, "{")
	arrayStart := strings.Index(trimmed, "[")

	start := -1
	closeChar := ""
	switch {
	case objectStart >= 0 && arrayStart >= 0:
		if objectStart < arrayStart {
			start = objectStart
			closeChar = "}"
		} else {
			start = arrayStart
			closeChar = "]"
		}
	case objectStart >= 0:
		start = objectStart
		closeChar = "}"
	case arrayStart >= 0:
		start = arrayStart
		closeChar = "]"
	default:
		return ""
	}

	end := strings.LastIndex(trimmed, closeChar)
	if end < start {
		return ""
	}
	return strings.TrimSpace(trimmed[start : end+1])
}

// validateStructuredJSON validates parsed JSON against the canonical schema.
func validateStructuredJSON(schemaRaw, parsed json.RawMessage) error {
	if len(schemaRaw) == 0 || len(parsed) == 0 {
		return nil
	}

	coreSchema, err := extractValidationSchema(schemaRaw)
	if err != nil {
		return err
	}

	compiler := jsonschema.NewCompiler()
	if err := compiler.AddResource("schema.json", bytes.NewReader(coreSchema)); err != nil {
		return fmt.Errorf("failed to load structured schema: %w", err)
	}
	schema, err := compiler.Compile("schema.json")
	if err != nil {
		return fmt.Errorf("failed to compile structured schema: %w", err)
	}

	var doc any
	if err := json.Unmarshal(parsed, &doc); err != nil {
		return fmt.Errorf("failed to decode structured JSON for validation: %w", err)
	}

	if err := schema.Validate(doc); err != nil {
		return fmt.Errorf("structured output does not match schema: %w", err)
	}
	return nil
}

func extractValidationSchema(schemaRaw json.RawMessage) (json.RawMessage, error) {
	var root any
	if err := json.Unmarshal(schemaRaw, &root); err != nil {
		return nil, fmt.Errorf("invalid structured schema JSON: %w", err)
	}

	if rootMap, ok := root.(map[string]any); ok {
		// Common OpenAI/OpenRouter wrapper: {"name","strict","schema":{...}}
		if inner, ok := rootMap["schema"]; ok {
			b, err := json.Marshal(inner)
			if err != nil {
				return nil, fmt.Errorf("failed to serialize inner schema: %w", err)
			}
			return b, nil
		}
		// Alternate wrapper: {"type":"json_schema","json_schema":{"schema":...}}
		if rawInner, ok := rootMap["json_schema"]; ok {
			if innerMap, ok := rawInner.(map[string]any); ok {
				if innerSchema, ok := innerMap["schema"]; ok {
					b, err := json.Marshal(innerSchema)
					if err != nil {
						return nil, fmt.Errorf("failed to serialize json_schema.schema: %w", err)
					}
					return b, nil
				}
			}
		}
	}

	// Assume raw schema document.
	return schemaRaw, nil
}

func structuredRepairPrompt(schemaRaw json.RawMessage, lastOutput string, issue error) string {
	schemaText := string(schemaRaw)
	lastOutput = strings.TrimSpace(lastOutput)
	if len(lastOutput) > 12000 {
		lastOutput = lastOutput[:12000] + "\n...[truncated]"
	}

	return fmt.Sprintf(`Return ONLY valid JSON (no markdown, no commentary) that strictly conforms to this schema.

Schema:
%s

Your previous output:
%s

Validation issue:
%v`, schemaText, lastOutput, issue)
}

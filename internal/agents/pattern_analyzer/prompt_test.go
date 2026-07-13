package pattern_analyzer

import "testing"

func TestJSONSchemaRequiresCompleteDiscoveryPattern(t *testing.T) {
	outer := JSONSchema()["json_schema"].(map[string]any)
	schema := outer["schema"].(map[string]any)
	properties := schema["properties"].(map[string]any)
	discovered := properties["discovered_patterns"].(map[string]any)
	items := discovered["items"].(map[string]any)
	required := items["required"].([]string)

	want := map[string]bool{
		"pattern_type": true, "level_name": true, "range_start": true,
		"range_end": true, "level": true, "heading_format": true, "reasoning": true,
	}
	if len(required) != len(want) {
		t.Fatalf("required fields = %v", required)
	}
	for _, field := range required {
		if !want[field] {
			t.Fatalf("unexpected required field %q", field)
		}
	}
	patternProperties := items["properties"].(map[string]any)
	for _, field := range []string{"level_name", "range_start", "range_end", "heading_format"} {
		property := patternProperties[field].(map[string]any)
		if property["type"] != "string" || property["minLength"] != 1 {
			t.Fatalf("%s schema = %#v, want non-empty string", field, property)
		}
	}
}

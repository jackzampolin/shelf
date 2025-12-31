package prompts

import (
	"crypto/sha256"
	"encoding/hex"
	"regexp"
	"sort"
)

// variablePattern matches Go template variable references like {{.VarName}} or {{ .VarName }}
// Also matches nested fields like {{.Book.Title}}
var variablePattern = regexp.MustCompile(`\{\{\s*\.([a-zA-Z_][a-zA-Z0-9_.]*)\s*\}\}`)

// ExtractVariables extracts template variable names from a Go template string.
// For example, "Hello {{.Name}}, you have {{.Count}} items" returns ["Count", "Name"].
// Nested fields like {{.Book.Title}} return "Book.Title".
func ExtractVariables(text string) []string {
	matches := variablePattern.FindAllStringSubmatch(text, -1)
	seen := make(map[string]bool)
	var vars []string

	for _, match := range matches {
		if len(match) > 1 {
			varName := match[1]
			if !seen[varName] {
				seen[varName] = true
				vars = append(vars, varName)
			}
		}
	}

	// Sort for consistent ordering
	sort.Strings(vars)
	return vars
}

// HashText returns a SHA256 hash of the text for change detection.
func HashText(text string) string {
	h := sha256.Sum256([]byte(text))
	return hex.EncodeToString(h[:])
}

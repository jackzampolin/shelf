package defra

import (
	"fmt"
	"regexp"
	"strings"
)

// IDPattern matches valid DefraDB document IDs (bae-<uuid> format) and simple identifiers.
// This is used to validate IDs before interpolation to prevent GraphQL injection.
var IDPattern = regexp.MustCompile(`^[a-zA-Z0-9_-]+$`)

// ValidateID checks if a string is safe to use as a document ID in GraphQL queries.
// Returns an error if the ID contains characters that could be used for injection.
func ValidateID(id string) error {
	if id == "" {
		return fmt.Errorf("empty ID")
	}
	if len(id) > 500 {
		return fmt.Errorf("ID too long: %d characters", len(id))
	}
	if !IDPattern.MatchString(id) {
		return fmt.Errorf("invalid ID format: contains unsafe characters")
	}
	return nil
}

// QueryBuilder helps construct safe, parameterized GraphQL queries.
// It uses GraphQL variables to prevent injection attacks.
type QueryBuilder struct {
	collection string
	filters    []filterDef
	fields     []string
	cid        string
	cidVarName string
	cidVarType string
	varIndex   int
}

type filterDef struct {
	field    string
	op       string
	varName  string
	varType  string
	value    any
	isNested bool // for nested object filters like actual_page { _docID }
}

// NewQuery creates a new QueryBuilder for the given collection.
func NewQuery(collection string) *QueryBuilder {
	return &QueryBuilder{
		collection: collection,
		fields:     []string{"_docID"},
	}
}

// Filter adds an equality filter.
func (q *QueryBuilder) Filter(field string, value any) *QueryBuilder {
	varName := q.nextVarName()
	q.filters = append(q.filters, filterDef{
		field:   field,
		op:      "_eq",
		varName: varName,
		varType: filterVarType(field, value),
		value:   value,
	})
	return q
}

// filterVarType returns the GraphQL variable type for an equality filter on a
// field. DefraDB v1.0 types relation foreign-key fields (_docID and the
// auto-generated _<rel>ID fields like _bookID, _tocID, _actual_pageID) as ID,
// not String — a String variable in an ID position is a query type error.
func filterVarType(field string, value any) string {
	if field == "_docID" || (strings.HasPrefix(field, "_") && strings.HasSuffix(field, "ID")) {
		return "ID"
	}
	return inferGraphQLType(value)
}

// WithCID scopes the query to a specific commit CID (historical version).
// This uses DefraDB's top-level `cid` argument.
func (q *QueryBuilder) WithCID(cid string) *QueryBuilder {
	if cid == "" {
		return q
	}
	if q.cidVarName == "" {
		q.cidVarName = q.nextVarName()
		// DefraDB v1.0 types the top-level `cid` argument as [ID!], not String.
		q.cidVarType = "[ID!]"
	}
	q.cid = cid
	return q
}

// Fields sets the fields to return (replaces default of just _docID).
func (q *QueryBuilder) Fields(fields ...string) *QueryBuilder {
	q.fields = fields
	return q
}

// Build returns the query string and variables map.
func (q *QueryBuilder) Build() (string, map[string]any) {
	// Build variable definitions
	var varDefs []string
	vars := make(map[string]any)

	for _, f := range q.filters {
		varDefs = append(varDefs, fmt.Sprintf("$%s: %s", f.varName, f.varType))
		vars[f.varName] = f.value
	}
	if q.cidVarName != "" {
		varDefs = append(varDefs, fmt.Sprintf("$%s: %s", q.cidVarName, q.cidVarType))
		// cid is typed [ID!]; pass the single CID as a one-element list.
		vars[q.cidVarName] = []string{q.cid}
	}

	// Build filter clause
	var filterParts []string
	for _, f := range q.filters {
		filterParts = append(filterParts, fmt.Sprintf("%s: {%s: $%s}", f.field, f.op, f.varName))
	}

	// Build query
	var query strings.Builder

	// Query header with variable definitions
	if len(varDefs) > 0 {
		query.WriteString(fmt.Sprintf("query(%s) ", strings.Join(varDefs, ", ")))
	}

	query.WriteString("{ ")
	query.WriteString(q.collection)

	var args []string
	if len(filterParts) > 0 {
		args = append(args, fmt.Sprintf("filter: {%s}", strings.Join(filterParts, ", ")))
	}
	if q.cidVarName != "" {
		args = append(args, fmt.Sprintf("cid: $%s", q.cidVarName))
	}
	if len(args) > 0 {
		query.WriteString(fmt.Sprintf("(%s)", strings.Join(args, ", ")))
	}

	// Add fields
	query.WriteString(" { ")
	query.WriteString(strings.Join(q.fields, " "))
	query.WriteString(" } }")

	return query.String(), vars
}

// nextVarName generates the next variable name.
func (q *QueryBuilder) nextVarName() string {
	name := fmt.Sprintf("v%d", q.varIndex)
	q.varIndex++
	return name
}

// inferGraphQLType infers the GraphQL type from a Go value.
func inferGraphQLType(v any) string {
	switch v.(type) {
	case string:
		return "String"
	case int, int32, int64:
		return "Int"
	case float32, float64:
		return "Float"
	case bool:
		return "Boolean"
	default:
		return "String" // Default to String
	}
}

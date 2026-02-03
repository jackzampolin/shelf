package defra

import (
	"context"
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

// SanitizeID validates an ID and returns it if safe, or panics if not.
// Use this for IDs that should always be valid (internal system IDs).
// For user-provided IDs, use ValidateID and handle the error.
func SanitizeID(id string) string {
	if err := ValidateID(id); err != nil {
		panic(fmt.Sprintf("invalid ID %q: %v", id, err))
	}
	return id
}

// SafeID validates an ID and returns it if safe, or returns empty string and error.
// This is the preferred function for validating IDs before use in queries.
func SafeID(id string) (string, error) {
	if err := ValidateID(id); err != nil {
		return "", err
	}
	return id, nil
}

// QueryBuilder helps construct safe, parameterized GraphQL queries.
// It uses GraphQL variables to prevent injection attacks.
type QueryBuilder struct {
	collection string
	filters    []filterDef
	fields     []string
	order      string
	limit      int
	offset     int
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
		varType: inferGraphQLType(value),
		value:   value,
	})
	return q
}

// WithCID scopes the query to a specific commit CID (historical version).
// This uses DefraDB's top-level `cid` argument.
func (q *QueryBuilder) WithCID(cid string) *QueryBuilder {
	if cid == "" {
		return q
	}
	if q.cidVarName == "" {
		q.cidVarName = q.nextVarName()
		q.cidVarType = "String"
	}
	q.cid = cid
	return q
}

// FilterIn adds an _in filter for matching any of the values.
func (q *QueryBuilder) FilterIn(field string, values []string) *QueryBuilder {
	varName := q.nextVarName()
	q.filters = append(q.filters, filterDef{
		field:   field,
		op:      "_in",
		varName: varName,
		varType: "[String!]",
		value:   values,
	})
	return q
}

// FilterGT adds a greater-than filter.
func (q *QueryBuilder) FilterGT(field string, value any) *QueryBuilder {
	varName := q.nextVarName()
	q.filters = append(q.filters, filterDef{
		field:   field,
		op:      "_gt",
		varName: varName,
		varType: inferGraphQLType(value),
		value:   value,
	})
	return q
}

// FilterLT adds a less-than filter.
func (q *QueryBuilder) FilterLT(field string, value any) *QueryBuilder {
	varName := q.nextVarName()
	q.filters = append(q.filters, filterDef{
		field:   field,
		op:      "_lt",
		varName: varName,
		varType: inferGraphQLType(value),
		value:   value,
	})
	return q
}

// FilterGTE adds a greater-than-or-equal filter.
func (q *QueryBuilder) FilterGTE(field string, value any) *QueryBuilder {
	varName := q.nextVarName()
	q.filters = append(q.filters, filterDef{
		field:   field,
		op:      "_gte",
		varName: varName,
		varType: inferGraphQLType(value),
		value:   value,
	})
	return q
}

// FilterLTE adds a less-than-or-equal filter.
func (q *QueryBuilder) FilterLTE(field string, value any) *QueryBuilder {
	varName := q.nextVarName()
	q.filters = append(q.filters, filterDef{
		field:   field,
		op:      "_lte",
		varName: varName,
		varType: inferGraphQLType(value),
		value:   value,
	})
	return q
}

// Fields sets the fields to return (replaces default of just _docID).
func (q *QueryBuilder) Fields(fields ...string) *QueryBuilder {
	q.fields = fields
	return q
}

// OrderBy sets the ordering.
func (q *QueryBuilder) OrderBy(field string, direction string) *QueryBuilder {
	q.order = fmt.Sprintf("{%s: %s}", field, direction)
	return q
}

// Limit sets the maximum number of results.
func (q *QueryBuilder) Limit(n int) *QueryBuilder {
	q.limit = n
	return q
}

// Offset sets the offset for pagination.
func (q *QueryBuilder) Offset(n int) *QueryBuilder {
	q.offset = n
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
		vars[q.cidVarName] = q.cid
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
	if q.order != "" {
		args = append(args, fmt.Sprintf("order: %s", q.order))
	}
	if q.limit > 0 {
		args = append(args, fmt.Sprintf("limit: %d", q.limit))
	}
	if q.offset > 0 {
		args = append(args, fmt.Sprintf("offset: %d", q.offset))
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

// Execute builds and executes the query on the given client.
func (q *QueryBuilder) Execute(ctx context.Context, client *Client) (*GQLResponse, error) {
	query, vars := q.Build()
	return client.Execute(ctx, query, vars)
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

// SafeQuery executes a parameterized query with a single filter.
// This is a convenience function for simple single-filter queries.
func SafeQuery(ctx context.Context, client *Client, collection, filterField string, filterValue any, fields ...string) (*GQLResponse, error) {
	qb := NewQuery(collection).Filter(filterField, filterValue)
	if len(fields) > 0 {
		qb.Fields(fields...)
	}
	return qb.Execute(ctx, client)
}

// SafeQueryByDocID executes a parameterized query filtering by _docID.
func SafeQueryByDocID(ctx context.Context, client *Client, collection, docID string, fields ...string) (*GQLResponse, error) {
	return SafeQuery(ctx, client, collection, "_docID", docID, fields...)
}

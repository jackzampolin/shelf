package api

import (
	"encoding/json"
	"fmt"
	"io"
	"os"

	"gopkg.in/yaml.v3"
)

// OutputFormat defines the output format for CLI commands.
type OutputFormat string

const (
	OutputFormatYAML OutputFormat = "yaml"
	OutputFormatJSON OutputFormat = "json"
)

// DefaultOutput is the default output format.
var DefaultOutput OutputFormat = OutputFormatYAML

// globalOutputFormat is set by the root command's --output flag.
var globalOutputFormat OutputFormat = OutputFormatYAML

// SetOutputFormat sets the global output format.
func SetOutputFormat(format string) {
	switch format {
	case "json":
		globalOutputFormat = OutputFormatJSON
	case "yaml":
		globalOutputFormat = OutputFormatYAML
	default:
		globalOutputFormat = DefaultOutput
	}
}

// GetOutputFormat returns the current global output format.
func GetOutputFormat() OutputFormat {
	return globalOutputFormat
}

// Output writes data to stdout in the configured format.
func Output(data any) error {
	return OutputTo(os.Stdout, globalOutputFormat, data)
}

// OutputAs writes data to stdout in the specified format.
func OutputAs(format OutputFormat, data any) error {
	return OutputTo(os.Stdout, format, data)
}

// OutputTo writes data to the given writer in the specified format.
func OutputTo(w io.Writer, format OutputFormat, data any) error {
	switch format {
	case OutputFormatJSON:
		enc := json.NewEncoder(w)
		enc.SetIndent("", "  ")
		return enc.Encode(data)
	case OutputFormatYAML:
		enc := yaml.NewEncoder(w)
		enc.SetIndent(2)
		defer enc.Close()
		return enc.Encode(data)
	default:
		return fmt.Errorf("unknown output format: %s", format)
	}
}

// IsStructuredOutput returns true if the output format is structured (JSON/YAML).
// This can be used by commands that want to provide human-friendly messages
// only when not in structured output mode.
func IsStructuredOutput() bool {
	return globalOutputFormat == OutputFormatJSON || globalOutputFormat == OutputFormatYAML
}

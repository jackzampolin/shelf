// Package types provides shared types used across multiple packages.
// This package has no dependencies on other shelf packages to avoid import cycles.
package types

// DetectionSource indicates where a chapter detection came from.
type DetectionSource string

const (
	// SourcePatternAnalysis indicates detection from page pattern analysis (running header clusters).
	SourcePatternAnalysis DetectionSource = "pattern_analysis"
	// SourceLabel indicates detection from page labeling (is_chapter_start flag).
	SourceLabel DetectionSource = "label"
)

// ConfidenceLevel indicates the confidence of a detection.
type ConfidenceLevel string

const (
	// ConfidenceHigh indicates high confidence in the detection.
	ConfidenceHigh ConfidenceLevel = "high"
	// ConfidenceMedium indicates medium confidence in the detection.
	ConfidenceMedium ConfidenceLevel = "medium"
	// ConfidenceLow indicates low confidence in the detection.
	ConfidenceLow ConfidenceLevel = "low"
)

// ParseConfidenceLevel converts a string to a ConfidenceLevel.
// Returns ConfidenceLow if the string is not recognized.
func ParseConfidenceLevel(s string) ConfidenceLevel {
	switch s {
	case "high":
		return ConfidenceHigh
	case "medium":
		return ConfidenceMedium
	case "low":
		return ConfidenceLow
	default:
		return ConfidenceLow
	}
}

// DetectedChapter represents a chapter detected from page pattern analysis or labels.
// This is GROUND TRUTH from actual page content, more reliable than ToC-based patterns.
type DetectedChapter struct {
	PageNum       int             // Page where chapter starts
	RunningHeader string          // Running header text from page pattern analysis
	ChapterTitle  string          // Chapter title if detected
	ChapterNumber *int            // Chapter number if numeric
	Source        DetectionSource // Where this detection came from
	Confidence    ConfidenceLevel // Confidence level of detection
}

// ChapterStartPage represents a page marked as chapter start during labeling.
type ChapterStartPage struct {
	PageNum       int    // Page number
	RunningHeader string // Running header text from label stage
}

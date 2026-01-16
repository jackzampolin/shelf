package epub

import (
	"fmt"
	"strings"
)

// AudioSegment represents timing data for a paragraph's audio.
type AudioSegment struct {
	ParagraphIdx  int
	DurationMS    int
	StartOffsetMS int
}

// ChapterAudio contains audio data for a chapter.
type ChapterAudio struct {
	ChapterID    string         // e.g., "ch_001"
	AudioFile    string         // e.g., "audio/ch_001.mp3"
	DurationMS   int            // Total chapter duration
	Segments     []AudioSegment // Paragraph-level timing
}

// generateSMIL creates a SMIL file for a chapter with audio synchronization.
// The SMIL maps each paragraph (id="p0", "p1", etc.) to its audio clip.
func generateSMIL(chapterID string, audio ChapterAudio) string {
	var sb strings.Builder

	sb.WriteString(`<?xml version="1.0" encoding="UTF-8"?>
<smil xmlns="http://www.w3.org/ns/SMIL" xmlns:epub="http://www.idpf.org/2007/ops" version="3.0">
  <body>
    <seq id="seq1" epub:textref="../chapters/`)
	sb.WriteString(chapterID)
	sb.WriteString(`.xhtml">
`)

	for _, seg := range audio.Segments {
		clipBegin := formatSMILTime(seg.StartOffsetMS)
		clipEnd := formatSMILTime(seg.StartOffsetMS + seg.DurationMS)

		sb.WriteString(fmt.Sprintf(`      <par id="par%d">
        <text src="../chapters/%s.xhtml#p%d"/>
        <audio src="%s" clipBegin="%s" clipEnd="%s"/>
      </par>
`, seg.ParagraphIdx, chapterID, seg.ParagraphIdx, audio.AudioFile, clipBegin, clipEnd))
	}

	sb.WriteString(`    </seq>
  </body>
</smil>
`)

	return sb.String()
}

// formatSMILTime converts milliseconds to SMIL time format (e.g., "12.345s").
func formatSMILTime(ms int) string {
	seconds := float64(ms) / 1000.0
	return fmt.Sprintf("%.3fs", seconds)
}

// calculateTotalDuration returns the total duration in milliseconds from segments.
func calculateTotalDuration(segments []AudioSegment) int {
	if len(segments) == 0 {
		return 0
	}
	last := segments[len(segments)-1]
	return last.StartOffsetMS + last.DurationMS
}

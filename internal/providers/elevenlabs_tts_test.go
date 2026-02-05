package providers

import (
	"encoding/json"
	"testing"
)

func TestParseOutputFormat(t *testing.T) {
	tests := []struct {
		name       string
		input      string
		container  string
		sampleRate int
	}{
		{
			name:       "mp3 format",
			input:      "mp3_44100_128",
			container:  "mp3",
			sampleRate: 44100,
		},
		{
			name:       "pcm format maps to wav",
			input:      "pcm_16000",
			container:  "wav",
			sampleRate: 16000,
		},
		{
			name:       "legacy mp3",
			input:      "mp3",
			container:  "mp3",
			sampleRate: 0,
		},
		{
			name:       "empty defaults",
			input:      "",
			container:  "mp3",
			sampleRate: 0,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			container, sampleRate := parseOutputFormat(tt.input)
			if container != tt.container {
				t.Fatalf("expected container=%q, got %q", tt.container, container)
			}
			if sampleRate != tt.sampleRate {
				t.Fatalf("expected sampleRate=%d, got %d", tt.sampleRate, sampleRate)
			}
		})
	}
}

func TestElevenLabsTTSRequestIncludesSpeed(t *testing.T) {
	req := elevenLabsTTSRequest{
		Text:    "hello",
		ModelID: "eleven_turbo_v2_5",
		VoiceSettings: elevenLabsVoiceSettings{
			Stability:       0.5,
			SimilarityBoost: 0.75,
			Style:           0.0,
			Speed:           1.1,
			UseSpeakerBoost: true,
		},
	}

	data, err := json.Marshal(req)
	if err != nil {
		t.Fatalf("failed to marshal request: %v", err)
	}

	var decoded map[string]any
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("failed to unmarshal request: %v", err)
	}

	voiceSettings, ok := decoded["voice_settings"].(map[string]any)
	if !ok {
		t.Fatal("expected voice_settings object")
	}
	if _, ok := voiceSettings["speed"]; !ok {
		t.Fatal("expected speed field in voice_settings")
	}
}

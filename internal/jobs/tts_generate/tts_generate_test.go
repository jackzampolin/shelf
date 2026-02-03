package tts_generate

import "testing"

func TestResolveAudioInclude(t *testing.T) {
	if !resolveAudioInclude(map[string]any{"audio_include": true}) {
		t.Fatal("expected audio_include=true to include")
	}
	if resolveAudioInclude(map[string]any{"audio_include": false}) {
		t.Fatal("expected audio_include=false to exclude")
	}
	if !resolveAudioInclude(map[string]any{"matter_type": "front_matter"}) {
		t.Fatal("expected front_matter to include by default")
	}
	if !resolveAudioInclude(map[string]any{"matter_type": "body"}) {
		t.Fatal("expected body to include by default")
	}
	if resolveAudioInclude(map[string]any{"matter_type": "back_matter"}) {
		t.Fatal("expected back_matter to exclude by default")
	}
	if !resolveAudioInclude(map[string]any{"matter_type": ""}) {
		t.Fatal("expected unknown matter_type to include by default")
	}
}

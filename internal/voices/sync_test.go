package voices

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/providers"
)

func TestVoiceSyncWriteCommitted(t *testing.T) {
	const syncedAt = "2026-07-10T22:09:32Z"
	wanted := providers.Voice{VoiceID: "voice-1", Name: "Narrator", Description: "Warm"}

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req defra.GQLRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Errorf("decode GraphQL request: %v", err)
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":{"Voice":[{"voice_id":"voice-1","name":"Narrator","description":"Warm","provider":"elevenlabs","synced_at":"2026-07-10T22:09:32Z"}]}}`))
	}))
	defer server.Close()

	if !voiceSyncWriteCommitted(context.Background(), defra.NewClient(server.URL), "elevenlabs", wanted, syncedAt) {
		t.Fatal("matching committed voice write was not recovered")
	}
}

func TestVoiceSyncWriteCommittedRejectsStaleRow(t *testing.T) {
	wanted := providers.Voice{VoiceID: "voice-1", Name: "Narrator", Description: "Warm"}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":{"Voice":[{"voice_id":"voice-1","name":"Old name","description":"Warm","provider":"elevenlabs","synced_at":"2026-07-10T22:09:32Z"}]}}`))
	}))
	defer server.Close()

	if voiceSyncWriteCommitted(context.Background(), defra.NewClient(server.URL), "elevenlabs", wanted, "2026-07-10T22:09:32Z") {
		t.Fatal("stale voice row was accepted as the requested write")
	}
}

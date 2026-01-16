package voices

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/providers"
)

// Voice represents a TTS voice stored in DefraDB.
type Voice struct {
	DocID       string `json:"_docID,omitempty"`
	VoiceID     string `json:"voice_id"`
	Name        string `json:"name"`
	Description string `json:"description,omitempty"`
	Provider    string `json:"provider"`
	IsDefault   bool   `json:"is_default"`
	CreatedAt   string `json:"created_at,omitempty"`
	SyncedAt    string `json:"synced_at,omitempty"`
}

// SyncConfig holds configuration for voice sync.
type SyncConfig struct {
	Client   *defra.Client
	Registry *providers.Registry
	Logger   *slog.Logger
}

// Sync fetches voices from configured TTS providers and syncs to DefraDB.
// It upserts voices based on voice_id, updating existing records and creating new ones.
func Sync(ctx context.Context, cfg SyncConfig) error {
	if cfg.Logger == nil {
		cfg.Logger = slog.Default()
	}

	// Find a TTS provider that can list voices
	var apiVoices []providers.Voice
	var providerName string
	var err error

	for name, provider := range cfg.Registry.TTSProviders() {
		if client, ok := provider.(*providers.ElevenLabsTTSClient); ok {
			cfg.Logger.Debug("found ElevenLabs TTS provider", "name", name)
			apiVoices, err = client.ListVoices(ctx)
			if err != nil {
				cfg.Logger.Warn("failed to fetch voices from ElevenLabs", "error", err)
				continue
			}
			providerName = providers.ElevenLabsTTSName
			break
		}
	}

	if len(apiVoices) == 0 {
		if providerName == "" {
			cfg.Logger.Debug("no TTS provider configured, skipping voice sync")
		} else {
			cfg.Logger.Info("no voices found from TTS provider", "provider", providerName)
		}
		return nil
	}

	cfg.Logger.Info("syncing voices from TTS provider", "provider", providerName, "count", len(apiVoices))

	// Sync each voice to database
	now := time.Now().UTC().Format(time.RFC3339)
	synced := 0
	for _, v := range apiVoices {
		// Filter: match by voice_id (DefraDB requires operator block format)
		filter := map[string]any{
			"voice_id": map[string]any{"_eq": v.VoiceID},
		}

		// Create input: all fields for new record
		createInput := map[string]any{
			"voice_id":    v.VoiceID,
			"name":        v.Name,
			"description": v.Description,
			"provider":    providerName,
			"is_default":  false,
			"synced_at":   now,
		}
		if v.CreatedAt != "" {
			createInput["created_at"] = v.CreatedAt
		}

		// Update input: only sync timestamp and potentially changed fields
		updateInput := map[string]any{
			"name":        v.Name,
			"description": v.Description,
			"synced_at":   now,
		}

		// Upsert the voice
		if _, err := cfg.Client.Upsert(ctx, "Voice", filter, createInput, updateInput); err != nil {
			cfg.Logger.Warn("failed to upsert voice", "voice_id", v.VoiceID, "error", err)
			continue
		}
		synced++
	}

	cfg.Logger.Info("voice sync complete", "synced", synced, "total", len(apiVoices))
	return nil
}

// List returns all voices from the database.
func List(ctx context.Context, client *defra.Client) ([]Voice, error) {
	query := `{
		Voice {
			_docID
			voice_id
			name
			description
			provider
			is_default
			created_at
			synced_at
		}
	}`

	resp, err := client.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("failed to query voices: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("graphql error: %s", errMsg)
	}

	return parseVoices(resp.Data)
}

// GetByVoiceID returns a voice by its provider voice ID.
func GetByVoiceID(ctx context.Context, client *defra.Client, voiceID string) (*Voice, error) {
	query := fmt.Sprintf(`{
		Voice(filter: {voice_id: {_eq: %q}}) {
			_docID
			voice_id
			name
			description
			provider
			is_default
			created_at
			synced_at
		}
	}`, voiceID)

	resp, err := client.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("failed to query voice: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("graphql error: %s", errMsg)
	}

	voices, err := parseVoices(resp.Data)
	if err != nil {
		return nil, err
	}
	if len(voices) == 0 {
		return nil, nil
	}

	return &voices[0], nil
}

// SetDefault marks a voice as the default, unsetting any previous default.
func SetDefault(ctx context.Context, client *defra.Client, voiceID string) error {
	// First, unset all defaults for this provider
	voices, err := List(ctx, client)
	if err != nil {
		return err
	}

	for _, v := range voices {
		if v.IsDefault {
			if err := client.Update(ctx, "Voice", v.DocID, map[string]any{
				"is_default": false,
			}); err != nil {
				return fmt.Errorf("failed to unset default: %w", err)
			}
		}
	}

	// Now set the new default
	voice, err := GetByVoiceID(ctx, client, voiceID)
	if err != nil {
		return err
	}
	if voice == nil {
		return fmt.Errorf("voice not found: %s", voiceID)
	}

	return client.Update(ctx, "Voice", voice.DocID, map[string]any{
		"is_default": true,
	})
}

// GetDefault returns the default voice, or nil if none set.
func GetDefault(ctx context.Context, client *defra.Client) (*Voice, error) {
	query := `{
		Voice(filter: {is_default: {_eq: true}}) {
			_docID
			voice_id
			name
			description
			provider
			is_default
			created_at
			synced_at
		}
	}`

	resp, err := client.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("failed to query default voice: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("graphql error: %s", errMsg)
	}

	voices, err := parseVoices(resp.Data)
	if err != nil {
		return nil, err
	}
	if len(voices) == 0 {
		return nil, nil
	}

	return &voices[0], nil
}

// parseVoices extracts Voice records from a GraphQL response.
func parseVoices(data map[string]any) ([]Voice, error) {
	voiceData, ok := data["Voice"]
	if !ok {
		return nil, nil
	}

	voiceSlice, ok := voiceData.([]any)
	if !ok {
		return nil, fmt.Errorf("unexpected Voice data type: %T", voiceData)
	}

	var voices []Voice
	for _, item := range voiceSlice {
		itemMap, ok := item.(map[string]any)
		if !ok {
			continue
		}

		// Re-marshal and unmarshal to handle type conversion
		jsonBytes, err := json.Marshal(itemMap)
		if err != nil {
			continue
		}

		var voice Voice
		if err := json.Unmarshal(jsonBytes, &voice); err != nil {
			continue
		}
		voices = append(voices, voice)
	}

	return voices, nil
}

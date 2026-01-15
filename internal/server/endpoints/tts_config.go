package endpoints

import (
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/svcctx"
	"github.com/jackzampolin/shelf/internal/voices"
)

// TTSVoice represents a voice option for TTS.
type TTSVoice struct {
	VoiceID     string `json:"voice_id"`
	Name        string `json:"name"`
	Description string `json:"description,omitempty"`
}

// TTSConfigResponse contains available TTS configuration options.
type TTSConfigResponse struct {
	Provider        string     `json:"provider"`
	Model           string     `json:"model"`
	DefaultVoice    string     `json:"default_voice,omitempty"`
	DefaultFormat   string     `json:"default_format"`
	Voices          []TTSVoice `json:"voices"`
	Formats         []string   `json:"formats"`
	VoiceCloningURL string     `json:"voice_cloning_url,omitempty"`
}

// GetTTSConfigEndpoint handles GET /api/tts/config.
type GetTTSConfigEndpoint struct{}

func (e *GetTTSConfigEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/tts/config", e.handler
}

func (e *GetTTSConfigEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get TTS configuration
//	@Description	Get available TTS voices, models, and formats
//	@Tags			tts
//	@Produce		json
//	@Success		200	{object}	TTSConfigResponse
//	@Failure		500	{object}	ErrorResponse
//	@Failure		503	{object}	ErrorResponse
//	@Router			/api/tts/config [get]
func (e *GetTTSConfigEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	client := svcctx.DefraClientFrom(ctx)
	registry := svcctx.RegistryFrom(ctx)

	if client == nil || registry == nil {
		writeError(w, http.StatusServiceUnavailable, "services not initialized")
		return
	}

	// Find DeepInfra TTS provider (may be registered under different names like "chatterbox")
	var deepInfraTTS *providers.DeepInfraTTSClient
	for _, provider := range registry.TTSProviders() {
		if client, ok := provider.(*providers.DeepInfraTTSClient); ok {
			deepInfraTTS = client
			break
		}
	}

	if deepInfraTTS == nil {
		writeError(w, http.StatusServiceUnavailable, "TTS provider not configured")
		return
	}

	// Get voices from database (synced on startup)
	var ttsVoices []TTSVoice
	voiceList, err := voices.List(ctx, client)
	if err != nil {
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Warn("failed to list voices from DB", "error", err)
		}
	} else {
		for _, v := range voiceList {
			ttsVoices = append(ttsVoices, TTSVoice{
				VoiceID:     v.VoiceID,
				Name:        v.Name,
				Description: v.Description,
			})
		}
	}

	// Get default voice from database, fall back to provider config
	defaultVoiceID := ""
	defaultVoice, _ := voices.GetDefault(ctx, client)
	if defaultVoice != nil {
		defaultVoiceID = defaultVoice.VoiceID
	} else if deepInfraTTS.Voice() != "" {
		defaultVoiceID = deepInfraTTS.Voice()
	}

	resp := TTSConfigResponse{
		Provider:        providers.DeepInfraTTSName,
		Model:           deepInfraTTS.Model(),
		DefaultVoice:    defaultVoiceID,
		DefaultFormat:   deepInfraTTS.Format(),
		Voices:          ttsVoices,
		Formats:         []string{"mp3", "wav", "opus", "flac"},
		VoiceCloningURL: "https://deepinfra.com/ResembleAI/chatterbox/voice",
	}

	writeJSON(w, http.StatusOK, resp)
}

func (e *GetTTSConfigEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "tts-config",
		Short: "Get TTS configuration and available voices",
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var resp TTSConfigResponse
			if err := client.Get(ctx, "/api/tts/config", &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
}

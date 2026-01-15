package endpoints

import (
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// TTSVoice represents a voice option for TTS.
type TTSVoice struct {
	VoiceID     string `json:"voice_id"`
	Name        string `json:"name"`
	Description string `json:"description,omitempty"`
}

// TTSConfigResponse contains available TTS configuration options.
type TTSConfigResponse struct {
	Provider       string     `json:"provider"`
	Model          string     `json:"model"`
	DefaultVoice   string     `json:"default_voice,omitempty"`
	DefaultFormat  string     `json:"default_format"`
	Voices         []TTSVoice `json:"voices"`
	Formats        []string   `json:"formats"`
	VoiceCloningURL string    `json:"voice_cloning_url,omitempty"`
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
	registry := svcctx.RegistryFrom(ctx)
	if registry == nil {
		writeError(w, http.StatusServiceUnavailable, "registry not initialized")
		return
	}

	// Get TTS provider from registry
	ttsProvider, err := registry.GetTTS(providers.DeepInfraTTSName)
	if err != nil {
		writeError(w, http.StatusServiceUnavailable, "TTS provider not configured: "+err.Error())
		return
	}

	// Cast to DeepInfraTTSClient to access ListVoices
	deepInfraTTS, ok := ttsProvider.(*providers.DeepInfraTTSClient)
	if !ok {
		writeError(w, http.StatusInternalServerError, "unexpected TTS provider type")
		return
	}

	// Fetch available voices from DeepInfra
	var voices []TTSVoice
	apiVoices, err := deepInfraTTS.ListVoices(ctx)
	if err != nil {
		// Log error but don't fail - just return empty voices list
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Warn("failed to list TTS voices", "error", err)
		}
	} else {
		for _, v := range apiVoices {
			voices = append(voices, TTSVoice{
				VoiceID:     v.VoiceID,
				Name:        v.Name,
				Description: v.Description,
			})
		}
	}

	resp := TTSConfigResponse{
		Provider:        providers.DeepInfraTTSName,
		Model:           deepInfraTTS.Model(),
		DefaultVoice:    deepInfraTTS.Voice(),
		DefaultFormat:   deepInfraTTS.Format(),
		Voices:          voices,
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

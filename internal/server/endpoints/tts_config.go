package endpoints

import (
	"net/http"
	"net/url"
	"sort"
	"strings"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/jobcfg"
	"github.com/jackzampolin/shelf/internal/jobs/tts_generate"
	"github.com/jackzampolin/shelf/internal/jobs/tts_generate_openai"
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
	Available       []string   `json:"available_providers,omitempty"`
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
//	@Param			provider	query		string	false	"TTS provider override"
//	@Success		200	{object}	TTSConfigResponse
//	@Failure		400	{object}	ErrorResponse
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
	requestedProvider := strings.ToLower(strings.TrimSpace(r.URL.Query().Get("provider")))

	// Resolve preferred provider from defaults if possible.
	preferredProvider := ""
	if configStore := svcctx.ConfigStoreFrom(ctx); configStore != nil {
		if cfg, err := jobcfg.NewBuilder(configStore).TTSConfig(ctx); err == nil {
			preferredProvider = strings.ToLower(strings.TrimSpace(cfg.TTSProvider))
		}
	}

	type providerConfig struct {
		Model           string
		DefaultVoice    string
		Format          string
		Formats         []string
		VoiceCloningURL string
	}
	availableProviders := make([]string, 0, len(registry.TTSProviders()))
	configByProvider := make(map[string]providerConfig, len(registry.TTSProviders()))

	resolveProvider := func(name string, provider providers.TTSProvider) (providerConfig, bool) {
		switch client := provider.(type) {
		case *providers.ElevenLabsTTSClient:
			return providerConfig{
				Model:           client.Model(),
				DefaultVoice:    client.Voice(),
				Format:          client.Format(),
				Formats:         tts_generate.SupportedStorytellerFormats(),
				VoiceCloningURL: "https://elevenlabs.io/voice-lab",
			}, true
		case *providers.OpenAITTSClient:
			return providerConfig{
				Model:        client.Model(),
				DefaultVoice: client.Voice(),
				Format:       "mp3",
				Formats:      tts_generate_openai.SupportedStorytellerFormats(),
			}, true
		default:
			return providerConfig{}, false
		}
	}

	for name, provider := range registry.TTSProviders() {
		name = strings.ToLower(strings.TrimSpace(name))
		if cfg, ok := resolveProvider(name, provider); ok {
			availableProviders = append(availableProviders, name)
			configByProvider[name] = cfg
		}
	}
	sort.Strings(availableProviders)

	if len(availableProviders) == 0 {
		writeError(w, http.StatusServiceUnavailable, "TTS provider not configured")
		return
	}

	if requestedProvider != "" {
		if _, ok := configByProvider[requestedProvider]; !ok {
			writeError(
				w,
				http.StatusBadRequest,
				"unsupported provider override "+requestedProvider+" (supported: "+strings.Join(availableProviders, ", ")+")",
			)
			return
		}
	}

	providerName := requestedProvider
	if providerName == "" {
		if preferredProvider != "" {
			if _, ok := configByProvider[preferredProvider]; ok {
				providerName = preferredProvider
			}
		}
	}
	if providerName == "" {
		providerName = availableProviders[0]
	}

	selectedConfig, ok := configByProvider[providerName]
	if !ok {
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
			if providerName != "" && !strings.EqualFold(v.Provider, providerName) {
				continue
			}
			ttsVoices = append(ttsVoices, TTSVoice{
				VoiceID:     v.VoiceID,
				Name:        v.Name,
				Description: v.Description,
			})
		}
	}

	// Get default voice from database, fall back to provider config
	defaultVoiceID := ""
	dbDefaultVoice, _ := voices.GetDefault(ctx, client)
	if dbDefaultVoice != nil && strings.EqualFold(dbDefaultVoice.Provider, providerName) {
		defaultVoiceID = dbDefaultVoice.VoiceID
	} else if selectedConfig.DefaultVoice != "" {
		defaultVoiceID = selectedConfig.DefaultVoice
	}

	resp := TTSConfigResponse{
		Provider:        providerName,
		Model:           selectedConfig.Model,
		DefaultVoice:    defaultVoiceID,
		DefaultFormat:   selectedConfig.Format,
		Available:       availableProviders,
		Voices:          ttsVoices,
		Formats:         selectedConfig.Formats,
		VoiceCloningURL: selectedConfig.VoiceCloningURL,
	}

	writeJSON(w, http.StatusOK, resp)
}

func (e *GetTTSConfigEndpoint) Command(getServerURL func() string) *cobra.Command {
	var provider string
	cmd := &cobra.Command{
		Use:   "tts-config",
		Short: "Get TTS configuration and available voices",
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			path := "/api/tts/config"
			if strings.TrimSpace(provider) != "" {
				path = path + "?provider=" + url.QueryEscape(strings.ToLower(strings.TrimSpace(provider)))
			}
			var resp TTSConfigResponse
			if err := client.Get(ctx, path, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&provider, "provider", "", "TTS provider override (elevenlabs or openai)")
	return cmd
}

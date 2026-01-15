package endpoints

import (
	"encoding/json"
	"net/http"
	"strings"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/svcctx"
	"github.com/jackzampolin/shelf/internal/voices"
)

// VoiceResponse represents a voice in API responses.
type VoiceResponse struct {
	VoiceID     string `json:"voice_id"`
	Name        string `json:"name"`
	Description string `json:"description,omitempty"`
	Provider    string `json:"provider"`
	IsDefault   bool   `json:"is_default"`
	CreatedAt   string `json:"created_at,omitempty"`
	SyncedAt    string `json:"synced_at,omitempty"`
}

// ListVoicesResponse contains the list of voices.
type ListVoicesResponse struct {
	Voices []VoiceResponse `json:"voices"`
}

// ListVoicesEndpoint handles GET /api/voices.
type ListVoicesEndpoint struct{}

func (e *ListVoicesEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/voices", e.handler
}

func (e *ListVoicesEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		List TTS voices
//	@Description	List all available TTS voices from the database
//	@Tags			voices
//	@Produce		json
//	@Success		200	{object}	ListVoicesResponse
//	@Failure		500	{object}	ErrorResponse
//	@Router			/api/voices [get]
func (e *ListVoicesEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	client := svcctx.DefraClientFrom(ctx)
	if client == nil {
		writeError(w, http.StatusServiceUnavailable, "database not initialized")
		return
	}

	voiceList, err := voices.List(ctx, client)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to list voices: "+err.Error())
		return
	}

	resp := ListVoicesResponse{
		Voices: make([]VoiceResponse, len(voiceList)),
	}
	for i, v := range voiceList {
		resp.Voices[i] = VoiceResponse{
			VoiceID:     v.VoiceID,
			Name:        v.Name,
			Description: v.Description,
			Provider:    v.Provider,
			IsDefault:   v.IsDefault,
			CreatedAt:   v.CreatedAt,
			SyncedAt:    v.SyncedAt,
		}
	}

	writeJSON(w, http.StatusOK, resp)
}

func (e *ListVoicesEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List TTS voices",
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var resp ListVoicesResponse
			if err := client.Get(ctx, "/api/voices", &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
}

// SyncVoicesEndpoint handles POST /api/voices/sync.
type SyncVoicesEndpoint struct{}

func (e *SyncVoicesEndpoint) Route() (string, string, http.HandlerFunc) {
	return "POST", "/api/voices/sync", e.handler
}

func (e *SyncVoicesEndpoint) RequiresInit() bool { return true }

// SyncVoicesResponse contains the sync result.
type SyncVoicesResponse struct {
	Message string `json:"message"`
	Synced  int    `json:"synced"`
}

// handler godoc
//
//	@Summary		Sync TTS voices
//	@Description	Sync voices from TTS provider to database
//	@Tags			voices
//	@Produce		json
//	@Success		200	{object}	SyncVoicesResponse
//	@Failure		500	{object}	ErrorResponse
//	@Router			/api/voices/sync [post]
func (e *SyncVoicesEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	client := svcctx.DefraClientFrom(ctx)
	registry := svcctx.RegistryFrom(ctx)
	logger := svcctx.LoggerFrom(ctx)

	if client == nil || registry == nil {
		writeError(w, http.StatusServiceUnavailable, "services not initialized")
		return
	}

	// Run sync
	if err := voices.Sync(ctx, voices.SyncConfig{
		Client:   client,
		Registry: registry,
		Logger:   logger,
	}); err != nil {
		writeError(w, http.StatusInternalServerError, "sync failed: "+err.Error())
		return
	}

	// Get updated count
	voiceList, _ := voices.List(ctx, client)

	writeJSON(w, http.StatusOK, SyncVoicesResponse{
		Message: "Voice sync complete",
		Synced:  len(voiceList),
	})
}

func (e *SyncVoicesEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "sync",
		Short: "Sync TTS voices from provider",
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var resp SyncVoicesResponse
			if err := client.Post(ctx, "/api/voices/sync", nil, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
}

// SetDefaultVoiceEndpoint handles PUT /api/voices/{voice_id}/default.
type SetDefaultVoiceEndpoint struct{}

func (e *SetDefaultVoiceEndpoint) Route() (string, string, http.HandlerFunc) {
	return "PUT", "/api/voices/", e.handler // Dynamic path handled in handler
}

func (e *SetDefaultVoiceEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Set default voice
//	@Description	Set a voice as the default TTS voice
//	@Tags			voices
//	@Produce		json
//	@Param			voice_id	path	string	true	"Voice ID"
//	@Success		200			{object}	map[string]string
//	@Failure		400			{object}	ErrorResponse
//	@Failure		404			{object}	ErrorResponse
//	@Failure		500			{object}	ErrorResponse
//	@Router			/api/voices/{voice_id}/default [put]
func (e *SetDefaultVoiceEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	client := svcctx.DefraClientFrom(ctx)
	if client == nil {
		writeError(w, http.StatusServiceUnavailable, "database not initialized")
		return
	}

	// Extract voice_id from path: /api/voices/{voice_id}/default
	path := strings.TrimPrefix(r.URL.Path, "/api/voices/")
	parts := strings.Split(path, "/")
	if len(parts) < 2 || parts[1] != "default" {
		writeError(w, http.StatusBadRequest, "invalid path")
		return
	}
	voiceID := parts[0]

	if voiceID == "" {
		writeError(w, http.StatusBadRequest, "voice_id required")
		return
	}

	if err := voices.SetDefault(ctx, client, voiceID); err != nil {
		if strings.Contains(err.Error(), "not found") {
			writeError(w, http.StatusNotFound, err.Error())
			return
		}
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, map[string]string{
		"message":  "Default voice updated",
		"voice_id": voiceID,
	})
}

func (e *SetDefaultVoiceEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "set-default <voice_id>",
		Short: "Set a voice as the default",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var resp map[string]string
			if err := client.Put(ctx, "/api/voices/"+args[0]+"/default", nil, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
}

// GetTTSConfigEndpoint now reads from database.
// Keeping separate since it includes provider info beyond just voices.
// Updated to use DB voices instead of API call.
func (e *GetTTSConfigEndpoint) handlerV2(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	client := svcctx.DefraClientFrom(ctx)
	registry := svcctx.RegistryFrom(ctx)

	if client == nil || registry == nil {
		writeError(w, http.StatusServiceUnavailable, "services not initialized")
		return
	}

	// Get TTS provider for model info
	ttsProvider, err := registry.GetTTS(providers.DeepInfraTTSName)
	if err != nil {
		writeError(w, http.StatusServiceUnavailable, "TTS provider not configured: "+err.Error())
		return
	}

	deepInfraTTS, ok := ttsProvider.(*providers.DeepInfraTTSClient)
	if !ok {
		writeError(w, http.StatusInternalServerError, "unexpected TTS provider type")
		return
	}

	// Get voices from database
	voiceList, err := voices.List(ctx, client)
	if err != nil {
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Warn("failed to list voices from DB", "error", err)
		}
	}

	// Get default voice
	defaultVoice, _ := voices.GetDefault(ctx, client)
	defaultVoiceID := ""
	if defaultVoice != nil {
		defaultVoiceID = defaultVoice.VoiceID
	} else if deepInfraTTS.Voice() != "" {
		// Fall back to provider default
		defaultVoiceID = deepInfraTTS.Voice()
	}

	// Build response
	ttsVoices := make([]TTSVoice, len(voiceList))
	for i, v := range voiceList {
		ttsVoices[i] = TTSVoice{
			VoiceID:     v.VoiceID,
			Name:        v.Name,
			Description: v.Description,
		}
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

// DeleteVoiceEndpoint handles DELETE /api/voices/{voice_id}.
// This removes a voice from the local DB (doesn't delete from provider).
type DeleteVoiceEndpoint struct{}

func (e *DeleteVoiceEndpoint) Route() (string, string, http.HandlerFunc) {
	return "DELETE", "/api/voices/", e.handler
}

func (e *DeleteVoiceEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Delete voice
//	@Description	Delete a voice from the local database
//	@Tags			voices
//	@Produce		json
//	@Param			voice_id	path	string	true	"Voice ID"
//	@Success		200			{object}	map[string]string
//	@Failure		404			{object}	ErrorResponse
//	@Failure		500			{object}	ErrorResponse
//	@Router			/api/voices/{voice_id} [delete]
func (e *DeleteVoiceEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	client := svcctx.DefraClientFrom(ctx)
	if client == nil {
		writeError(w, http.StatusServiceUnavailable, "database not initialized")
		return
	}

	// Extract voice_id from path
	voiceID := strings.TrimPrefix(r.URL.Path, "/api/voices/")
	if voiceID == "" || strings.Contains(voiceID, "/") {
		writeError(w, http.StatusBadRequest, "voice_id required")
		return
	}

	// Get the voice to find its DocID
	voice, err := voices.GetByVoiceID(ctx, client, voiceID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	if voice == nil {
		writeError(w, http.StatusNotFound, "voice not found")
		return
	}

	// Delete from database
	if err := client.Delete(ctx, "Voice", voice.DocID); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to delete: "+err.Error())
		return
	}

	writeJSON(w, http.StatusOK, map[string]string{
		"message":  "Voice deleted",
		"voice_id": voiceID,
	})
}

func (e *DeleteVoiceEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "delete <voice_id>",
		Short: "Delete a voice from local database",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			if err := client.Delete(ctx, "/api/voices/"+args[0]); err != nil {
				return err
			}
			return api.Output(map[string]string{
				"message":  "Voice deleted",
				"voice_id": args[0],
			})
		},
	}
}

// CreateVoiceRequest for adding a custom voice.
type CreateVoiceRequest struct {
	VoiceID     string `json:"voice_id"`
	Name        string `json:"name"`
	Description string `json:"description,omitempty"`
}

// CreateVoiceEndpoint handles POST /api/voices.
type CreateVoiceEndpoint struct{}

func (e *CreateVoiceEndpoint) Route() (string, string, http.HandlerFunc) {
	return "POST", "/api/voices", e.handler
}

func (e *CreateVoiceEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Create voice
//	@Description	Add a custom voice to the database
//	@Tags			voices
//	@Accept			json
//	@Produce		json
//	@Param			request	body		CreateVoiceRequest	true	"Voice details"
//	@Success		201		{object}	VoiceResponse
//	@Failure		400		{object}	ErrorResponse
//	@Failure		500		{object}	ErrorResponse
//	@Router			/api/voices [post]
func (e *CreateVoiceEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	client := svcctx.DefraClientFrom(ctx)
	if client == nil {
		writeError(w, http.StatusServiceUnavailable, "database not initialized")
		return
	}

	var req CreateVoiceRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON: "+err.Error())
		return
	}

	if req.VoiceID == "" {
		writeError(w, http.StatusBadRequest, "voice_id required")
		return
	}
	if req.Name == "" {
		req.Name = req.VoiceID // Default name to voice_id
	}

	// Check if voice already exists
	existing, _ := voices.GetByVoiceID(ctx, client, req.VoiceID)
	if existing != nil {
		writeError(w, http.StatusConflict, "voice already exists")
		return
	}

	// Create the voice
	doc := map[string]any{
		"voice_id":    req.VoiceID,
		"name":        req.Name,
		"description": req.Description,
		"provider":    providers.DeepInfraTTSName,
		"is_default":  false,
	}

	docID, err := client.Create(ctx, "Voice", doc)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to create: "+err.Error())
		return
	}

	writeJSON(w, http.StatusCreated, VoiceResponse{
		VoiceID:     req.VoiceID,
		Name:        req.Name,
		Description: req.Description,
		Provider:    providers.DeepInfraTTSName,
		IsDefault:   false,
	})
	_ = docID // unused but returned for potential future use
}

func (e *CreateVoiceEndpoint) Command(getServerURL func() string) *cobra.Command {
	var name, description string
	cmd := &cobra.Command{
		Use:   "create <voice_id>",
		Short: "Add a custom voice",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			req := CreateVoiceRequest{
				VoiceID:     args[0],
				Name:        name,
				Description: description,
			}
			var resp VoiceResponse
			if err := client.Post(ctx, "/api/voices", req, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&name, "name", "", "Voice name")
	cmd.Flags().StringVar(&description, "description", "", "Voice description")
	return cmd
}

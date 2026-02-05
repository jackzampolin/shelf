package endpoints

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/url"
	"sort"
	"strings"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/config"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// SettingsResponse contains all config entries grouped by prefix.
type SettingsResponse struct {
	Settings map[string]config.Entry `json:"settings"`
}

// SettingResponse contains a single config entry.
type SettingResponse struct {
	Entry *config.Entry `json:"entry,omitempty"`
	Error string        `json:"error,omitempty"`
}

// UpdateSettingRequest is the request body for updating a setting.
type UpdateSettingRequest struct {
	Value       any    `json:"value"`
	Description string `json:"description,omitempty"`
}

// ListSettingsEndpoint handles GET /api/settings.
type ListSettingsEndpoint struct{}

func (e *ListSettingsEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/settings", e.handler
}

func (e *ListSettingsEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		List all settings
//	@Description	Get all configuration settings
//	@Tags			settings
//	@Produce		json
//	@Success		200	{object}	SettingsResponse
//	@Failure		500	{object}	ErrorResponse
//	@Router			/api/settings [get]
func (e *ListSettingsEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	store := svcctx.ConfigStoreFrom(r.Context())
	if store == nil {
		writeError(w, http.StatusInternalServerError, "config store not available")
		return
	}

	entries, err := store.GetAll(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, SettingsResponse{Settings: entries})
}

func (e *ListSettingsEndpoint) Command(getServerURL func() string) *cobra.Command {
	var prefix string
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List all settings",
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var resp SettingsResponse
			if err := client.Get(ctx, "/api/settings", &resp); err != nil {
				return err
			}

			// Filter by prefix if specified
			if prefix != "" {
				filtered := make(map[string]config.Entry)
				for k, v := range resp.Settings {
					if strings.HasPrefix(k, prefix) {
						filtered[k] = v
					}
				}
				resp.Settings = filtered
			}

			// Sort keys for consistent output
			keys := make([]string, 0, len(resp.Settings))
			for k := range resp.Settings {
				keys = append(keys, k)
			}
			sort.Strings(keys)

			// Output sorted
			sorted := make(map[string]config.Entry)
			for _, k := range keys {
				sorted[k] = resp.Settings[k]
			}
			return api.Output(sorted)
		},
	}
	cmd.Flags().StringVar(&prefix, "prefix", "", "Filter by key prefix (e.g., 'providers.ocr.')")
	return cmd
}

// GetSettingEndpoint handles GET /api/settings/{key...}.
type GetSettingEndpoint struct{}

func (e *GetSettingEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/settings/{key...}", e.handler
}

func (e *GetSettingEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get a setting
//	@Description	Get a single configuration setting by key
//	@Tags			settings
//	@Produce		json
//	@Param			key	path		string	true	"Setting key (URL-encoded)"
//	@Success		200	{object}	SettingResponse
//	@Failure		404	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Router			/api/settings/{key} [get]
func (e *GetSettingEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	key, err := url.PathUnescape(r.PathValue("key"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid key encoding")
		return
	}
	if err := config.ValidateKey(key); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	store := svcctx.ConfigStoreFrom(r.Context())
	if store == nil {
		writeError(w, http.StatusInternalServerError, "config store not available")
		return
	}

	entry, err := store.Get(r.Context(), key)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	if entry == nil {
		writeError(w, http.StatusNotFound, "setting not found")
		return
	}

	writeJSON(w, http.StatusOK, SettingResponse{Entry: entry})
}

func (e *GetSettingEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "get <key>",
		Short: "Get a setting by key",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			key := args[0]
			client := api.NewClient(getServerURL())
			var resp SettingResponse
			path := "/api/settings/" + url.PathEscape(key)
			if err := client.Get(ctx, path, &resp); err != nil {
				return err
			}
			return api.Output(resp.Entry)
		},
	}
}

// UpdateSettingEndpoint handles PUT /api/settings/{key...}.
type UpdateSettingEndpoint struct{}

func (e *UpdateSettingEndpoint) Route() (string, string, http.HandlerFunc) {
	return "PUT", "/api/settings/{key...}", e.handler
}

func (e *UpdateSettingEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Update a setting
//	@Description	Update a configuration setting
//	@Tags			settings
//	@Accept			json
//	@Produce		json
//	@Param			key		path		string				true	"Setting key (URL-encoded)"
//	@Param			body	body		UpdateSettingRequest	true	"New value"
//	@Success		200		{object}	SettingResponse
//	@Failure		400		{object}	ErrorResponse
//	@Failure		500		{object}	ErrorResponse
//	@Router			/api/settings/{key} [put]
func (e *UpdateSettingEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	key, err := url.PathUnescape(r.PathValue("key"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid key encoding")
		return
	}
	if err := config.ValidateKey(key); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	var req UpdateSettingRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body: "+err.Error())
		return
	}

	store := svcctx.ConfigStoreFrom(r.Context())
	if store == nil {
		writeError(w, http.StatusInternalServerError, "config store not available")
		return
	}

	// Get existing for description if not provided
	existing, err := store.Get(r.Context(), key)
	if err != nil {
		// Log but don't fail - the user explicitly wants to set a value
		if logger := svcctx.LoggerFrom(r.Context()); logger != nil {
			logger.Warn("failed to fetch existing setting for description preservation",
				"key", key, "error", err)
		}
	}
	description := req.Description
	if description == "" && existing != nil {
		description = existing.Description
	}

	if err := store.Set(r.Context(), key, req.Value, description); err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	// Return updated entry
	entry, err := store.Get(r.Context(), key)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, SettingResponse{Entry: entry})
}

func (e *UpdateSettingEndpoint) Command(getServerURL func() string) *cobra.Command {
	var value string
	var description string
	cmd := &cobra.Command{
		Use:   "set <key>",
		Short: "Update a setting",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			key := args[0]
			client := api.NewClient(getServerURL())

			// Parse value as JSON
			var parsedValue any
			if err := json.Unmarshal([]byte(value), &parsedValue); err != nil {
				// If not valid JSON, treat as string
				parsedValue = value
			}

			req := UpdateSettingRequest{
				Value:       parsedValue,
				Description: description,
			}
			var resp SettingResponse
			path := "/api/settings/" + url.PathEscape(key)
			if err := client.Put(ctx, path, req, &resp); err != nil {
				return err
			}
			return api.Output(resp.Entry)
		},
	}
	cmd.Flags().StringVar(&value, "value", "", "New value (JSON or string)")
	cmd.Flags().StringVar(&description, "description", "", "Description (optional)")
	_ = cmd.MarkFlagRequired("value")
	return cmd
}

// ResetSettingEndpoint handles POST /api/settings/reset/{key...}.
type ResetSettingEndpoint struct{}

func (e *ResetSettingEndpoint) Route() (string, string, http.HandlerFunc) {
	return "POST", "/api/settings/reset/{key...}", e.handler
}

func (e *ResetSettingEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Reset a setting to default
//	@Description	Reset a configuration setting to its default value
//	@Tags			settings
//	@Produce		json
//	@Param			key	path		string	true	"Setting key (URL-encoded)"
//	@Success		200	{object}	SettingResponse
//	@Failure		400	{object}	ErrorResponse
//	@Failure		404	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Router			/api/settings/reset/{key} [post]
func (e *ResetSettingEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	key, err := url.PathUnescape(r.PathValue("key"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid key encoding")
		return
	}
	if err := config.ValidateKey(key); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	store := svcctx.ConfigStoreFrom(r.Context())
	if store == nil {
		writeError(w, http.StatusInternalServerError, "config store not available")
		return
	}

	// Reset to default
	if err := config.ResetToDefault(r.Context(), store, key); err != nil {
		if errors.Is(err, config.ErrNoDefault) {
			writeError(w, http.StatusNotFound, err.Error())
		} else {
			writeError(w, http.StatusInternalServerError, err.Error())
		}
		return
	}

	// Return reset entry
	entry, err := store.Get(r.Context(), key)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, SettingResponse{Entry: entry})
}

func (e *ResetSettingEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "reset <key>",
		Short: "Reset a setting to its default value",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			key := args[0]
			client := api.NewClient(getServerURL())
			var resp SettingResponse
			path := "/api/settings/reset/" + url.PathEscape(key)
			if err := client.Post(ctx, path, nil, &resp); err != nil {
				return err
			}
			return api.Output(resp.Entry)
		},
	}
}

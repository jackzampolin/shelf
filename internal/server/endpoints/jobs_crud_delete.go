package endpoints

import (
	"errors"
	"fmt"
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// DeleteJobEndpoint handles DELETE /api/jobs/{id}.
type DeleteJobEndpoint struct{}

func (e *DeleteJobEndpoint) Route() (string, string, http.HandlerFunc) {
	return "DELETE", "/api/jobs/{id}", e.handler
}

func (e *DeleteJobEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Delete a job
//	@Description	Delete a job by ID
//	@Tags			jobs
//	@Param			id	path	string	true	"Job ID"
//	@Success		204	"No Content"
//	@Failure		400	{object}	ErrorResponse
//	@Failure		404	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Failure		503	{object}	ErrorResponse
//	@Router			/api/jobs/{id} [delete]
func (e *DeleteJobEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if id == "" {
		writeError(w, http.StatusBadRequest, "job id is required")
		return
	}

	jm := svcctx.JobManagerFrom(r.Context())
	if jm == nil {
		writeError(w, http.StatusServiceUnavailable, "job manager not initialized")
		return
	}

	if err := jm.Delete(r.Context(), id); err != nil {
		if errors.Is(err, jobs.ErrNotFound) {
			writeError(w, http.StatusNotFound, "job not found")
			return
		}
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	w.WriteHeader(http.StatusNoContent)
}

func (e *DeleteJobEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "delete <id>",
		Short: "Delete a job by ID",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			if err := client.Delete(ctx, "/api/jobs/"+args[0]); err != nil {
				return err
			}
			fmt.Println("Job deleted successfully")
			return nil
		},
	}
}

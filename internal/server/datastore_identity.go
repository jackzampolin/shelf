package server

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"path/filepath"
	"strings"

	"github.com/jackzampolin/shelf/internal/config"
)

const datastoreIdentityKey = "system.datastore_identity"

type datastoreIdentityStore interface {
	Get(context.Context, string) (*config.Entry, error)
}

type datastoreIdentityCreator interface {
	Create(context.Context, string, map[string]any) (string, error)
}

// canonicalDatastoreIdentity binds a Defra datastore to one canonical Shelf
// home without persisting the local filesystem path itself.
func canonicalDatastoreIdentity(homePath string) (string, error) {
	abs, err := filepath.Abs(homePath)
	if err != nil {
		return "", fmt.Errorf("resolve Shelf home: %w", err)
	}
	real, err := filepath.EvalSymlinks(abs)
	if err != nil {
		return "", fmt.Errorf("resolve Shelf home symlinks: %w", err)
	}
	sum := sha256.Sum256([]byte(filepath.Clean(real)))
	return "shelf-home-sha256:" + hex.EncodeToString(sum[:]), nil
}

// ensureDatastoreIdentity fails closed if the Defra endpoint answers with a
// datastore claimed by another Shelf home. Claim is create-only: concurrent
// starts can never overwrite the winner's identity and both verify the value
// returned by Defra before any config seeding or job resumption begins.
func ensureDatastoreIdentity(
	ctx context.Context,
	store datastoreIdentityStore,
	creator datastoreIdentityCreator,
	homePath string,
) (claimed bool, err error) {
	expected, err := canonicalDatastoreIdentity(homePath)
	if err != nil {
		return false, err
	}

	entry, err := store.Get(ctx, datastoreIdentityKey)
	if err != nil {
		return false, fmt.Errorf("read datastore identity: %w", err)
	}
	if entry == nil {
		valueJSON, err := json.Marshal(expected)
		if err != nil {
			return false, fmt.Errorf("encode datastore identity: %w", err)
		}
		_, createErr := creator.Create(ctx, "Config", map[string]any{
			"name":        datastoreIdentityKey,
			"value":       string(valueJSON),
			"description": "Canonical Shelf home identity; prevents cross-home Defra attachment",
		})
		if createErr != nil && !strings.Contains(strings.ToLower(createErr.Error()), "already exists") {
			return false, fmt.Errorf("claim datastore identity: %w", createErr)
		}
		claimed = createErr == nil
		entry, err = store.Get(ctx, datastoreIdentityKey)
		if err != nil {
			return false, fmt.Errorf("verify claimed datastore identity: %w", err)
		}
		if entry == nil {
			return false, fmt.Errorf("claimed datastore identity is not readable")
		}
	}

	actual, ok := entry.Value.(string)
	if !ok || actual == "" {
		return false, fmt.Errorf("invalid datastore identity value %T", entry.Value)
	}
	if actual != expected {
		return false, fmt.Errorf(
			"Defra datastore belongs to another Shelf home (expected %s, got %s)",
			expected,
			actual,
		)
	}
	return claimed, nil
}

package server

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/jackzampolin/shelf/internal/config"
)

type identityTestStore struct {
	entry *config.Entry
	err   error
}

func (s *identityTestStore) Get(context.Context, string) (*config.Entry, error) {
	return s.entry, s.err
}

type identityTestCreator struct {
	store       *identityTestStore
	createErr   error
	created     int
	racingValue string
}

func (c *identityTestCreator) Create(_ context.Context, collection string, input map[string]any) (string, error) {
	c.created++
	if collection != "Config" {
		return "", errors.New("unexpected collection")
	}
	if c.racingValue != "" {
		c.store.entry = &config.Entry{Key: datastoreIdentityKey, Value: c.racingValue}
	} else if value, ok := input["value"].(string); ok {
		c.store.entry = &config.Entry{Key: datastoreIdentityKey, Value: strings.Trim(value, `"`)}
	}
	return "identity-doc", c.createErr
}

func TestCanonicalDatastoreIdentityResolvesSymlinks(t *testing.T) {
	real := t.TempDir()
	link := filepath.Join(t.TempDir(), "home-link")
	if err := os.Symlink(real, link); err != nil {
		t.Fatal(err)
	}
	realID, err := canonicalDatastoreIdentity(real)
	if err != nil {
		t.Fatal(err)
	}
	linkID, err := canonicalDatastoreIdentity(link)
	if err != nil {
		t.Fatal(err)
	}
	if realID != linkID {
		t.Fatalf("real identity %q != symlink identity %q", realID, linkID)
	}
	if strings.Contains(realID, real) {
		t.Fatal("identity must not expose the local Shelf home path")
	}
}

func TestEnsureDatastoreIdentityClaimsAndVerifies(t *testing.T) {
	home := t.TempDir()
	store := &identityTestStore{}
	creator := &identityTestCreator{store: store}
	claimed, err := ensureDatastoreIdentity(context.Background(), store, creator, home)
	if err != nil {
		t.Fatal(err)
	}
	if !claimed || creator.created != 1 {
		t.Fatalf("claimed=%v creates=%d, want true/1", claimed, creator.created)
	}
	claimed, err = ensureDatastoreIdentity(context.Background(), store, creator, home)
	if err != nil {
		t.Fatal(err)
	}
	if claimed || creator.created != 1 {
		t.Fatalf("second claimed=%v creates=%d, want false/1", claimed, creator.created)
	}
}

func TestEnsureDatastoreIdentityRejectsOtherHome(t *testing.T) {
	first := t.TempDir()
	second := t.TempDir()
	firstID, err := canonicalDatastoreIdentity(first)
	if err != nil {
		t.Fatal(err)
	}
	store := &identityTestStore{entry: &config.Entry{Value: firstID}}
	creator := &identityTestCreator{store: store}
	_, err = ensureDatastoreIdentity(context.Background(), store, creator, second)
	if err == nil || !strings.Contains(err.Error(), "belongs to another Shelf home") {
		t.Fatalf("error = %v, want cross-home rejection", err)
	}
	if creator.created != 0 {
		t.Fatalf("creator called %d times on mismatch", creator.created)
	}
}

func TestEnsureDatastoreIdentityLosesClaimRaceWithoutOverwrite(t *testing.T) {
	home := t.TempDir()
	other := t.TempDir()
	otherID, err := canonicalDatastoreIdentity(other)
	if err != nil {
		t.Fatal(err)
	}
	store := &identityTestStore{}
	creator := &identityTestCreator{
		store:       store,
		createErr:   errors.New("document already exists"),
		racingValue: otherID,
	}
	_, err = ensureDatastoreIdentity(context.Background(), store, creator, home)
	if err == nil || !strings.Contains(err.Error(), "belongs to another Shelf home") {
		t.Fatalf("error = %v, want lost-race mismatch", err)
	}
	if store.entry.Value != otherID {
		t.Fatal("losing claimant overwrote the winning identity")
	}
}

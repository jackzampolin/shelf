package researchmcp

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"time"
)

type Client struct {
	baseURL string
	http    *http.Client
}

func NewClient(baseURL string, httpClient *http.Client) *Client {
	if httpClient == nil {
		httpClient = &http.Client{Timeout: 2 * time.Minute}
	}
	return &Client{baseURL: strings.TrimRight(baseURL, "/"), http: httpClient}
}

func (c *Client) get(ctx context.Context, path string, out any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+path, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "application/json")
	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("shelf GET %s: %w", path, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("shelf GET %s returned %s: %s", path, resp.Status, strings.TrimSpace(string(body)))
	}
	if err := json.NewDecoder(resp.Body).Decode(out); err != nil {
		return fmt.Errorf("decode shelf GET %s: %w", path, err)
	}
	return nil
}

func (c *Client) loadSnapshot(ctx context.Context, bookID string) (*snapshot, error) {
	if strings.TrimSpace(bookID) == "" {
		return nil, fmt.Errorf("book_id is required")
	}
	var selected book
	bookPath := "/api/books/" + url.PathEscape(bookID)
	if err := c.get(ctx, bookPath, &selected); err != nil {
		return nil, err
	}
	if selected.ID != bookID {
		return nil, fmt.Errorf("Shelf returned book %q for requested book %q", selected.ID, bookID)
	}

	var chapters chaptersResponse
	path := "/api/books/" + url.PathEscape(bookID) + "/chapters?include_paragraphs=true"
	if err := c.get(ctx, path, &chapters); err != nil {
		return nil, err
	}
	sort.Slice(chapters.Chapters, func(i, j int) bool {
		return chapters.Chapters[i].SortOrder < chapters.Chapters[j].SortOrder
	})

	var passages []passage
	h := sha256.New()
	fmt.Fprintf(h, "shelf-research-v1\x00%s\x00%s\x00", selected.ID, selected.SourceSHA256)
	for _, ch := range chapters.Chapters {
		fmt.Fprintf(h, "chapter\x00%s\x00%d\x00%s\x00%d\x00%d\x00", ch.ID, ch.SortOrder, ch.Title, ch.StartPage, ch.EndPage)
		sort.Slice(ch.Paragraphs, func(i, j int) bool {
			return ch.Paragraphs[i].SortOrder < ch.Paragraphs[j].SortOrder
		})
		if len(ch.Paragraphs) == 0 {
			text := strings.TrimSpace(ch.PolishedText)
			if text == "" {
				continue
			}
			p := makePassage(ch, "", ch.StartPage, text)
			passages = append(passages, p)
			fmt.Fprintf(h, "passage\x00%s\x00%s\x00%s\x00", p.ChapterID, p.ParagraphID, p.Text)
			continue
		}
		for _, para := range ch.Paragraphs {
			text := strings.TrimSpace(para.PolishedText)
			if text == "" {
				text = strings.TrimSpace(para.RawText)
			}
			if text == "" {
				continue
			}
			p := makePassage(ch, para.ID, para.StartPage, text)
			passages = append(passages, p)
			fmt.Fprintf(h, "passage\x00%s\x00%s\x00%s\x00", p.ChapterID, p.ParagraphID, p.Text)
		}
	}

	return &snapshot{
		Book:            selected,
		Chapters:        chapters.Chapters,
		Passages:        passages,
		StructureDigest: "sha256:" + hex.EncodeToString(h.Sum(nil)),
	}, nil
}

func makePassage(ch chapter, paragraphID string, startPage int, text string) passage {
	sum := sha256.Sum256([]byte(text))
	return passage{
		ChapterID:    ch.ID,
		ParagraphID:  paragraphID,
		ChapterTitle: ch.Title,
		MatterType:   ch.MatterType,
		StartPage:    startPage,
		Text:         text,
		ContentHash:  "sha256:" + hex.EncodeToString(sum[:]),
	}
}

func requireResearchReady(s *snapshot) error {
	if !s.Book.StructureComplete || s.Book.StructureFailed {
		return fmt.Errorf("book %q is not research-ready: structure_complete=%t structure_failed=%t status=%q", s.Book.ID, s.Book.StructureComplete, s.Book.StructureFailed, s.Book.Status)
	}
	if len(s.Passages) == 0 {
		return fmt.Errorf("book %q has no canonical parsed passages", s.Book.ID)
	}
	return nil
}

package providers

import (
	"sync/atomic"
	"time"
)

// EndpointPool round-robins across a fixed set of base URLs.
// It is safe for concurrent use.
type EndpointPool struct {
	urls          []string
	indexByURL    map[string]int
	cooldownUntil []atomic.Int64
	counter       atomic.Uint64
}

// NewEndpointPool creates a pool over a copy of the given base URLs.
// An empty or nil slice yields a pool whose Next returns "".
func NewEndpointPool(urls []string) *EndpointPool {
	cp := make([]string, len(urls))
	copy(cp, urls)

	indexByURL := make(map[string]int, len(cp))
	for i, url := range cp {
		indexByURL[url] = i
	}

	return &EndpointPool{
		urls:          cp,
		indexByURL:    indexByURL,
		cooldownUntil: make([]atomic.Int64, len(cp)),
	}
}

// Len returns the number of endpoints.
func (p *EndpointPool) Len() int {
	return len(p.urls)
}

// Next returns the next base URL in round-robin order, or "" if the pool is empty.
func (p *EndpointPool) Next() string {
	n := uint64(len(p.urls))
	if n == 0 {
		return ""
	}
	start := p.counter.Add(1) - 1
	now := time.Now().UnixNano()
	for offset := uint64(0); offset < n; offset++ {
		i := (start + offset) % n
		if p.cooldownUntil[i].Load() <= now {
			return p.urls[i]
		}
	}
	return p.urls[start%n]
}

// MarkFailure temporarily deprioritizes an endpoint. If every endpoint is in
// cooldown, Next still returns one so callers do not deadlock waiting for
// recovery.
func (p *EndpointPool) MarkFailure(url string, cooldown time.Duration) {
	if cooldown <= 0 {
		return
	}
	i, ok := p.indexByURL[url]
	if !ok {
		return
	}
	until := time.Now().Add(cooldown).UnixNano()
	for {
		current := p.cooldownUntil[i].Load()
		if current >= until || p.cooldownUntil[i].CompareAndSwap(current, until) {
			return
		}
	}
}

// MarkSuccess clears any failure cooldown for an endpoint.
func (p *EndpointPool) MarkSuccess(url string) {
	i, ok := p.indexByURL[url]
	if !ok {
		return
	}
	p.cooldownUntil[i].Store(0)
}

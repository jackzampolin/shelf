package providers

import "sync/atomic"

// EndpointPool round-robins across a fixed set of base URLs.
// It is safe for concurrent use.
type EndpointPool struct {
	urls    []string
	counter atomic.Uint64
}

// NewEndpointPool creates a pool over a copy of the given base URLs.
// An empty or nil slice yields a pool whose Next returns "".
func NewEndpointPool(urls []string) *EndpointPool {
	cp := make([]string, len(urls))
	copy(cp, urls)
	return &EndpointPool{urls: cp}
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
	i := p.counter.Add(1) - 1
	return p.urls[i%n]
}

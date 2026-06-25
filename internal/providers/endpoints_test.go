package providers

import (
	"sync"
	"testing"
)

func TestEndpointPool_RoundRobin(t *testing.T) {
	p := NewEndpointPool([]string{"a", "b", "c"})
	got := []string{p.Next(), p.Next(), p.Next(), p.Next()}
	want := []string{"a", "b", "c", "a"}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("Next() sequence = %v, want %v", got, want)
		}
	}
}

func TestEndpointPool_Single(t *testing.T) {
	p := NewEndpointPool([]string{"only"})
	if p.Next() != "only" || p.Next() != "only" {
		t.Fatalf("single-endpoint pool must always return 'only'")
	}
}

func TestEndpointPool_Empty(t *testing.T) {
	p := NewEndpointPool(nil)
	if p.Len() != 0 {
		t.Fatalf("Len() = %d, want 0", p.Len())
	}
	if got := p.Next(); got != "" {
		t.Fatalf("Next() on empty pool = %q, want empty string", got)
	}
}

func TestEndpointPool_ConcurrentSafe(t *testing.T) {
	p := NewEndpointPool([]string{"a", "b"})
	var wg sync.WaitGroup
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_ = p.Next()
		}()
	}
	wg.Wait()
}

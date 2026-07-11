package providers

import (
	"sync"
	"testing"
	"time"
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

func TestEndpointPool_AcquireUsesLeastBusyEndpoint(t *testing.T) {
	p := NewEndpointPool([]string{"a", "b", "c"})
	first := p.Acquire()
	second := p.Acquire()
	third := p.Acquire()
	if first != "a" || second != "b" || third != "c" {
		t.Fatalf("initial Acquire() sequence = [%s %s %s], want [a b c]", first, second, third)
	}

	// All three have one request. The tie-breaker chooses a; once c is
	// released, the next reservation must choose c even though round-robin
	// order would otherwise start at b.
	fourth := p.Acquire()
	if fourth != "a" {
		t.Fatalf("fourth Acquire() = %q, want a", fourth)
	}
	p.Release(third)
	if got := p.Acquire(); got != "c" {
		t.Fatalf("Acquire() with c least busy = %q, want c", got)
	}
}

func TestEndpointPool_AcquireSkipsCooldown(t *testing.T) {
	p := NewEndpointPool([]string{"a", "b"})
	p.MarkFailure("a", time.Hour)

	first := p.Acquire()
	second := p.Acquire()
	if first != "b" || second != "b" {
		t.Fatalf("Acquire() with a cooling down = [%s %s], want [b b]", first, second)
	}
	p.Release(first)
	p.Release(second)
}

func TestEndpointPool_Status(t *testing.T) {
	p := NewEndpointPool([]string{"a", "b"})
	acquired := p.Acquire()
	p.MarkFailure("b", time.Hour)

	status := p.Status()
	if len(status) != 2 || status[0].BaseURL != "a" || status[1].BaseURL != "b" {
		t.Fatalf("Status() = %#v, want stable [a b] order", status)
	}
	if acquired != "a" || status[0].InFlight != 1 {
		t.Fatalf("a status = %#v after acquiring %q, want one in flight", status[0], acquired)
	}
	if status[1].CooldownUntil == nil || status[1].CooldownUntil.IsZero() {
		t.Fatalf("b status = %#v, want active cooldown", status[1])
	}

	p.Release(acquired)
	if got := p.Status()[0].InFlight; got != 0 {
		t.Fatalf("a in_flight after release = %d, want 0", got)
	}
}

func TestEndpointPool_SkipsFailedEndpointDuringCooldown(t *testing.T) {
	p := NewEndpointPool([]string{"a", "b"})
	p.MarkFailure("a", time.Hour)

	for i := 0; i < 4; i++ {
		if got := p.Next(); got != "b" {
			t.Fatalf("Next() with a in cooldown = %q, want b", got)
		}
	}

	p.MarkSuccess("a")
	got := []string{p.Next(), p.Next()}
	if got[0] != "a" || got[1] != "b" {
		t.Fatalf("Next() after MarkSuccess = %v, want [a b]", got)
	}
}

func TestEndpointPool_AllEndpointsInCooldownStillReturnsEndpoint(t *testing.T) {
	p := NewEndpointPool([]string{"a", "b"})
	p.MarkFailure("a", time.Hour)
	p.MarkFailure("b", time.Hour)

	if got := p.Next(); got != "a" && got != "b" {
		t.Fatalf("Next() with all endpoints in cooldown = %q, want one endpoint", got)
	}
}

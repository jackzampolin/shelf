package jobs

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"testing"
	"time"

	"github.com/jackzampolin/shelf/internal/providers"
)

// ctrlOCRProvider is a fully controllable OCR provider for circuit tests.
type ctrlOCRProvider struct {
	mu          sync.Mutex
	down        bool // ProcessImage fails with a transport error while true
	healthDown  bool // HealthCheck fails while true
	contentFail bool // ProcessImage fails with a non-retriable content error
	calls       int
	healthCalls int
}

type internallyRetryingOCRProvider struct {
	*ctrlOCRProvider
}

func (p *internallyRetryingOCRProvider) MaxRetries() int      { return 3 }
func (p *internallyRetryingOCRProvider) ManagesRetries() bool { return true }

func (f *ctrlOCRProvider) setDown(down bool) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.down = down
	f.healthDown = down
}

func (f *ctrlOCRProvider) callCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.calls
}

func newCtrlProvider() *ctrlOCRProvider { return &ctrlOCRProvider{} }

// errBackendDown matches IsRetriableError's transport class ("connection refused").
var errBackendDown = errors.New("dial tcp 100.74.68.88:8001: connect: connection refused")

func (f *ctrlOCRProvider) ProcessImage(ctx context.Context, image []byte, pageNum int) (*providers.OCRResult, error) {
	f.mu.Lock()
	f.calls++
	down, content := f.down, f.contentFail
	f.mu.Unlock()
	if down {
		return nil, errBackendDown
	}
	if content {
		// Deterministic content failure: NOT retriable per IsRetriableError.
		return &providers.OCRResult{Success: false, ErrorMessage: "page unreadable"},
			errors.New("chandra OCR failed (page 1): page unreadable")
	}
	return &providers.OCRResult{Success: true, Text: "ok"}, nil
}

func (f *ctrlOCRProvider) Name() string                  { return "ctrl" }
func (f *ctrlOCRProvider) RequestsPerSecond() float64    { return 1000 }
func (f *ctrlOCRProvider) MaxConcurrency() int           { return 2 }
func (f *ctrlOCRProvider) MaxRetries() int               { return 0 }
func (f *ctrlOCRProvider) RetryDelayBase() time.Duration { return time.Millisecond }

func (f *ctrlOCRProvider) HealthCheck(ctx context.Context) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.healthCalls++
	if f.healthDown {
		return errBackendDown
	}
	return nil
}

func TestCircuitTripsAndPausesDispatch(t *testing.T) {
	prov := newCtrlProvider()
	prov.setDown(true)

	pool, results := newTestPool(t, prov, circuitConfig{
		TripThreshold: 3,
		ProbeInterval: 20 * time.Millisecond,
		ParkMaxAge:    time.Hour,
		ParkCapacity:  16,
	})
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go pool.Start(ctx)

	// 3 units, MaxRetries=0 -> 3 consecutive infra failures -> circuit opens.
	for i := 0; i < 3; i++ {
		mustSubmit(t, pool, ocrUnit(fmt.Sprintf("u%d", i)))
	}

	waitFor(t, time.Second, func() bool { return pool.Status().Health != healthHealthy })

	// While open, newly submitted units must NOT reach the provider.
	before := prov.callCount()
	mustSubmit(t, pool, ocrUnit("paused"))
	time.Sleep(100 * time.Millisecond)
	if got := prov.callCount(); got != before {
		t.Fatalf("provider called %d times while circuit open, want %d (no calls)", got, before)
	}
	drain(results)
}

func TestExplicitDispatchPauseHoldsWorkUntilResume(t *testing.T) {
	prov := newCtrlProvider()
	pool, _ := newTestPool(t, prov, circuitConfig{
		TripThreshold: 3,
		ProbeInterval: time.Second,
		ParkMaxAge:    time.Hour,
		ParkCapacity:  16,
	})
	pool.pauseDispatch()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go pool.Start(ctx)

	mustSubmit(t, pool, ocrUnit("held"))
	time.Sleep(50 * time.Millisecond)
	if got := prov.callCount(); got != 0 {
		t.Fatalf("provider called %d times while dispatch explicitly paused", got)
	}

	pool.resumeDispatch()
	waitFor(t, time.Second, func() bool { return prov.callCount() == 1 })
}

func TestContentErrorsDoNotTripCircuit(t *testing.T) {
	prov := newCtrlProvider()
	prov.contentFail = true // non-retriable failures

	pool, results := newTestPool(t, prov, circuitConfig{
		TripThreshold: 2,
		ProbeInterval: 20 * time.Millisecond,
		ParkMaxAge:    time.Hour,
		ParkCapacity:  16,
	})
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go pool.Start(ctx)

	for i := 0; i < 6; i++ {
		mustSubmit(t, pool, ocrUnit(fmt.Sprintf("c%d", i)))
	}
	// All 6 must come back as ordinary failures with the circuit still closed.
	for i := 0; i < 6; i++ {
		res := recvResult(t, results, time.Second)
		if res.Result.Success {
			t.Fatal("content failure reported as success")
		}
	}
	if h := pool.Status().Health; h != healthHealthy {
		t.Fatalf("circuit tripped on content errors: health=%q", h)
	}
}

func TestProviderManagedRetriesAreNotMultipliedByPool(t *testing.T) {
	base := newCtrlProvider()
	base.setDown(true)
	prov := &internallyRetryingOCRProvider{ctrlOCRProvider: base}
	pool, err := NewProviderWorkerPool(ProviderWorkerPoolConfig{
		Name:        "internal-retry",
		OCRProvider: prov,
		WorkerCount: 1,
	})
	if err != nil {
		t.Fatal(err)
	}
	pool.circuit.cfg.TripThreshold = 99

	result, parked := pool.process(context.Background(), ocrUnit("single-budget"))
	if result.Success || parked {
		t.Fatalf("result = success:%v parked:%v, want ordinary failure", result.Success, parked)
	}
	if got := base.callCount(); got != 1 {
		t.Fatalf("provider calls = %d, want 1 outer call; provider owns its retry budget", got)
	}
}

func TestProviderPoolReportsPerJobUnitLocation(t *testing.T) {
	pool, err := NewProviderWorkerPool(ProviderWorkerPoolConfig{
		Name:        "located",
		OCRProvider: newCtrlProvider(),
		WorkerCount: 1,
	})
	if err != nil {
		t.Fatal(err)
	}
	pool.init(make(chan workerResult, 8))
	for _, id := range []string{"queued-a", "queued-b"} {
		unit := ocrUnit(id)
		unit.JobID = "job-located"
		mustSubmit(t, pool, unit)
	}
	pool.claim("job-located")
	parked := ocrUnit("parked")
	parked.JobID = "job-located"
	if err := pool.circuit.park(parked, errBackendDown); err != nil {
		t.Fatal(err)
	}

	got := pool.JobWorkStatus("job-located")
	if got.Queued != 2 || got.InFlight != 1 || got.Parked != 1 {
		t.Fatalf("JobWorkStatus() = %+v, want queued=2 in_flight=1 parked=1", got)
	}
	pool.release("job-located")
}

func TestProviderPoolDoesNotPrefetchIntoHiddenWorkerBuffer(t *testing.T) {
	pool, err := NewProviderWorkerPool(ProviderWorkerPoolConfig{
		Name:        "unbuffered",
		OCRProvider: newCtrlProvider(),
		WorkerCount: 2,
	})
	if err != nil {
		t.Fatal(err)
	}
	pool.init(make(chan workerResult, 8))
	if got := cap(pool.work); got != 0 {
		t.Fatalf("internal worker queue capacity = %d, want 0 so fair dispatch tracks worker availability", got)
	}
}

func TestParkAndReplayOnRecovery(t *testing.T) {
	prov := newCtrlProvider()
	prov.setDown(true)

	pool, results := newTestPool(t, prov, circuitConfig{
		TripThreshold: 1,
		ProbeInterval: 20 * time.Millisecond,
		ParkMaxAge:    time.Hour,
		ParkCapacity:  16,
	})
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go pool.Start(ctx)

	// Threshold 1: the tripping failure and the park decision are atomic, so
	// the very first infra failure parks its unit instead of failing through.
	mustSubmit(t, pool, ocrUnit("p0"))
	waitFor(t, time.Second, func() bool { return pool.Status().Health != healthHealthy })

	select {
	case res := <-results:
		t.Fatalf("unit %s failed through while circuit open; want parked", res.Result.WorkUnitID)
	case <-time.After(150 * time.Millisecond):
	}

	// Recover the backend: circuit closes, the parked unit replays, succeeds.
	prov.setDown(false)
	res := recvResult(t, results, 2*time.Second)
	if !res.Result.Success {
		t.Fatalf("replayed unit %s failed: %v", res.Result.WorkUnitID, res.Result.Error)
	}
	if res.Result.WorkUnitID != "p0" {
		t.Fatalf("replayed unit = %s, want p0", res.Result.WorkUnitID)
	}
	if h := pool.Status().Health; h != healthHealthy {
		t.Fatalf("circuit still open after recovery: %q", h)
	}
}

func TestParkExpiryFailsThrough(t *testing.T) {
	prov := newCtrlProvider()
	prov.setDown(true)

	pool, results := newTestPool(t, prov, circuitConfig{
		TripThreshold: 1,
		ProbeInterval: 20 * time.Millisecond,
		ParkMaxAge:    60 * time.Millisecond, // expire quickly; backend never recovers
		ParkCapacity:  16,
	})
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go pool.Start(ctx)

	mustSubmit(t, pool, ocrUnit("exp0")) // trips (threshold 1) and parks

	// The parked unit must eventually fail through with its original error.
	res := recvResult(t, results, 2*time.Second)
	if res.Result.Success {
		t.Fatal("expired parked unit reported success")
	}
	if res.Result.Error == nil {
		t.Fatal("expired parked unit missing error")
	}
}

func TestParkCapacityOverflowFailsThrough(t *testing.T) {
	prov := newCtrlProvider()
	prov.setDown(true)

	pool, results := newTestPool(t, prov, circuitConfig{
		TripThreshold: 1,
		ProbeInterval: time.Hour, // never recovers during test
		ParkMaxAge:    time.Hour,
		ParkCapacity:  1, // only one unit may park
	})
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go pool.Start(ctx)

	mustSubmit(t, pool, ocrUnit("full0")) // trips circuit, parks
	waitFor(t, time.Second, func() bool { return pool.Status().ParkedUnits == 1 })

	// Force a second failing unit through the open circuit is impossible
	// (dispatch is paused), so overflow applies to units already in workers.
	// Submit before pause is racy; instead assert the invariant directly:
	if !errors.Is(pool.circuit.park(ocrUnit("full1"), errBackendDown), errParkFull) {
		t.Fatal("second park should overflow (capacity 1)")
	}
	drain(results)
}

func TestDefaultParkedWorkDoesNotExpire(t *testing.T) {
	c := &circuit{cfg: circuitConfig{ParkMaxAge: 0, ParkCapacity: 2}}
	c.parked = []parkedUnit{{
		unit:     ocrUnit("old"),
		err:      errBackendDown,
		parkedAt: time.Now().Add(-24 * time.Hour),
	}}
	if expired := c.expireParked(); len(expired) != 0 {
		t.Fatalf("default durable provider wait expired %d units, want 0", len(expired))
	}
	if _, parked := c.status(); parked != 1 {
		t.Fatalf("parked units = %d, want old work retained", parked)
	}
}

func TestProviderCircuitReportsWaitingAndRecoveryPerJob(t *testing.T) {
	prov := newCtrlProvider()
	prov.setDown(true)
	pool, results := newTestPool(t, prov, circuitConfig{
		TripThreshold: 1,
		ProbeInterval: 10 * time.Millisecond,
		ParkMaxAge:    0,
		ParkCapacity:  8,
	})
	type event struct {
		jobID   string
		waiting bool
	}
	events := make(chan event, 4)
	pool.onWaitChange = func(_ string, jobID string, waiting bool) {
		events <- event{jobID: jobID, waiting: waiting}
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go pool.Start(ctx)
	mustSubmit(t, pool, ocrUnit("wait-state"))

	select {
	case got := <-events:
		if got.jobID != "job-1" || !got.waiting {
			t.Fatalf("open event = %#v, want job-1 waiting", got)
		}
	case <-time.After(time.Second):
		t.Fatal("no waiting_provider callback after circuit opened")
	}

	prov.setDown(false)
	if result := recvResult(t, results, time.Second); !result.Result.Success {
		t.Fatalf("replayed work failed: %v", result.Result.Error)
	}
	select {
	case got := <-events:
		if got.jobID != "job-1" || got.waiting {
			t.Fatalf("recovery event = %#v, want job-1 running", got)
		}
	case <-time.After(time.Second):
		t.Fatal("no recovery callback after circuit closed")
	}
}

// --- helpers ---

func waitFor(t *testing.T, timeout time.Duration, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("condition not met before timeout")
}

func recvResult(t *testing.T, results chan workerResult, timeout time.Duration) workerResult {
	t.Helper()
	select {
	case res := <-results:
		return res
	case <-time.After(timeout):
		t.Fatal("timed out waiting for worker result")
		return workerResult{}
	}
}

func drain(results chan workerResult) {
	for {
		select {
		case <-results:
		default:
			return
		}
	}
}

func mustSubmit(t *testing.T, pool *ProviderWorkerPool, unit *WorkUnit) {
	t.Helper()
	if err := pool.Submit(unit); err != nil {
		t.Fatal(err)
	}
}

func ocrUnit(id string) *WorkUnit {
	return &WorkUnit{
		ID:         id,
		Type:       WorkUnitTypeOCR,
		JobID:      "job-1",
		OCRRequest: &OCRWorkRequest{Image: []byte{1}, PageNum: 1},
	}
}

func newTestPool(t *testing.T, prov *ctrlOCRProvider, cfg circuitConfig) (*ProviderWorkerPool, chan workerResult) {
	t.Helper()
	pool, err := NewProviderWorkerPool(ProviderWorkerPoolConfig{
		Name:        "ctrl",
		OCRProvider: prov,
		RPS:         1000,
		WorkerCount: 2,
		Logger:      slog.Default(),
	})
	if err != nil {
		t.Fatal(err)
	}
	pool.circuit.cfg = cfg
	results := make(chan workerResult, 64)
	pool.init(results)
	return pool, results
}

package jobs

import (
	"testing"
	"time"
)

func TestBookIsStranded(t *testing.T) {
	now := time.Now().UTC()
	cases := []struct {
		name     string
		active   bool
		records  []*Record
		stranded bool
	}{
		{"active in-memory job", true, []*Record{{Status: StatusFailed}}, false},
		{"failed only, no active", false, []*Record{{Status: StatusFailed}}, true},
		{"running record present", false, []*Record{{Status: StatusRunning}, {Status: StatusFailed}}, false},
		{"waiting-provider record present", false, []*Record{{Status: StatusWaitingProvider}, {Status: StatusFailed}}, false},
		{"queued record present", false, []*Record{{Status: StatusQueued}}, false},
		{"completed only", false, []*Record{{Status: StatusCompleted}}, false},
		{"no records", false, nil, false},
		{"recent failed record gets replacement grace", false, []*Record{{Status: StatusFailed, CompletedAt: timePtr(now)}}, false},
		{"old failed record is stranded", false, []*Record{{Status: StatusFailed, CompletedAt: timePtr(now.Add(-reconcileStrandGrace - time.Second))}}, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := bookIsStranded(tc.active, tc.records, now); got != tc.stranded {
				t.Fatalf("bookIsStranded = %v, want %v", got, tc.stranded)
			}
		})
	}
}

func timePtr(value time.Time) *time.Time { return &value }

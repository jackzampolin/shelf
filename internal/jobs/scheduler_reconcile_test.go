package jobs

import "testing"

func TestBookIsStranded(t *testing.T) {
	cases := []struct {
		name     string
		active   bool
		records  []*Record
		stranded bool
	}{
		{"active in-memory job", true, []*Record{{Status: StatusFailed}}, false},
		{"failed only, no active", false, []*Record{{Status: StatusFailed}}, true},
		{"running record present", false, []*Record{{Status: StatusRunning}, {Status: StatusFailed}}, false},
		{"queued record present", false, []*Record{{Status: StatusQueued}}, false},
		{"completed only", false, []*Record{{Status: StatusCompleted}}, false},
		{"no records", false, nil, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := bookIsStranded(tc.active, tc.records); got != tc.stranded {
				t.Fatalf("bookIsStranded = %v, want %v", got, tc.stranded)
			}
		})
	}
}

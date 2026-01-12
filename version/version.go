package version

// Build information. Populated at build-time via ldflags.
var (
	GoInfo        = "unknown"
	GitRelease    = "unknown"
	GitCommit     = "unknown"
	GitCommitDate = "unknown"
)

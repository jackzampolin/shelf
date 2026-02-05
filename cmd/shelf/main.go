package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"
)

func main() {
	// Set up context with manual signal handling for resilient shutdown.
	// Unlike signal.NotifyContext, this keeps catching signals after the first one,
	// preventing double Ctrl+C from bypassing the shutdown chain.
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigCh := make(chan os.Signal, 2)
	signal.Notify(sigCh, os.Interrupt, syscall.SIGTERM)

	go func() {
		<-sigCh // First signal: trigger graceful shutdown
		cancel()
		<-sigCh // Second signal: force exit
		fmt.Fprintln(os.Stderr, "\nForced exit")
		os.Exit(1)
	}()

	if err := rootCmd.ExecuteContext(ctx); err != nil {
		os.Exit(1)
	}
}

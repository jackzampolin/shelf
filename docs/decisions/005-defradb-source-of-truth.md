# 5. DefraDB as Source of Truth

**Date:** 2025-12-15

**Status:** Accepted

## Decision

**All state lives in DefraDB. Every change is verifiable.**

## Why DefraDB

| Feature | Benefit |
|---------|---------|
| **Merkle DAG** | Every change has a CID (content identifier) |
| **Full History** | Query any document's complete change history |
| **Cryptographic Proofs** | Verify data integrity, trace issues to source |
| **CRDT Conflict Resolution** | Multi-writer safety for parallel processing |
| **GraphQL API** | Query progress, filter by status |

## Data Provenance

Every document change creates an immutable block:
- **CID** (SHA256 content hash) - unique identifier
- **Parent links** - chain of previous states
- **Optional signatures** - ED25519/ECDSA authorship proof

When OCR output is wrong, trace back through the commit history to find which operation wrote the bad data and what input produced it.

## What This Replaces

Python used filesystem as database. Files existed = work done. No history, no verification.

Go uses DefraDB. Full audit trail. Cryptographic proof of every change.

## Core Principle

**Verifiable history enables debugging. CIDs don't lie.**

# ADR-016: Atomic material processing errors

- **Status**: Accepted
- **Date**: 2026-10-06
- **Related**: Guguță ADR-0002 (job queue), ADR-0007 (RLS), ADR-011 (PDF parsing)

## Context

An uploaded PDF exhausted five retries while the OCR container was stopped.
The job became `failed`, but its notebook source remained `processing`, so the
interface kept displaying processing and the manual retry endpoint refused it.
The handler only updated the source for explicitly permanent errors. Queue
expiry and publication failures had the same risk. Updating the source in a
separate transaction can race a manual retry or leave inconsistent state.

## Decision

The PostgreSQL queue publishes terminal material errors in the same transaction
as the job failure, using the job's stored owner as the transaction-local RLS
actor. This applies to permanent errors, exhausted transient retries, and the
claim sweep for expired leases, exhausted budgets, and deadlines. Only material
processing jobs update their linked sources, and only sources still processing
are changed. The job row lock serializes this update with manual retries.

The material handler uses this common failure path for extraction, dependency,
and publication failures. Existing lease-token and target-revision checks reject
stale handlers. Terminal failures record `completed_at`; manual retries clear
it along with the prior attempt and lease state. Actor context is restored
before the queue transaction continues.

## Consequences

No schema migration, embedding change, or reindexing is required. A temporary
outage still receives bounded automatic retries; if those fail, the interface
shows the existing error and retry controls. Database failure rolls back both
status changes. Failed source updates no longer silently commit only the job.
This does not prevent operators from explicitly stopping an OCR container;
operators must verify OCR readiness as well as API readiness during deployment.

Regression tests cover OCR and publication outages, successful manual recovery,
all three expiry paths, transaction rollback, and a stale failure after retry.

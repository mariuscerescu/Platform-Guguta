"""Guguță foundation — PostgreSQL persistence layer (ADR-0001, ADR-0007).

This package is the new persistence stack for Platforma Guguță. It does NOT
import surrealdb / surreal-commands; the legacy Open Notebook stack lives in
`open_notebook/database/` and stays until delivery L8.
"""

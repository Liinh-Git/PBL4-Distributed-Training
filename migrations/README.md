# Database Migrations

This directory will contain database schema migration scripts for the PBL4 Management Backend.

## Policy & Architecture

1. **Canonical Schema Projection**: Migration tooling is not selected or implemented by the scaffold. Any migration result must faithfully project the canonical PostgreSQL Data Model (`03. Mô hình dữ liệu`).
2. **Psycopg Stack**: The application repository layer uses `psycopg` with explicit SQL. Migration tooling must not introduce ORM abstractions or redefine application persistence architecture.
3. **Introduction**: Migration tooling and initial migration scripts will be introduced when Management Backend persistence implementation begins.
4. **Git Tracking**: All future migration scripts must be committed and tracked in version control.

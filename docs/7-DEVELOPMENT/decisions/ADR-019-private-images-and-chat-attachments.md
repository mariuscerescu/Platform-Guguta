# ADR-019: Images and private conversation attachments

Date: 2026-10-07 · Status: Accepted

Students need to add photographs to permanent notebook materials and attach
documents or images to a conversation. The agent must inspect the original
pixels and search extracted text. Conversation attachments must disappear
when that conversation is deleted.

Reuse the source/material/artifact/chunk/embedding pipeline. A nullable
`notebook_sources.chat_session_id` distinguishes permanent materials from
attachments; `chat_message_id` associates an uploaded file with its user
message. Uploads are initially staged, then bound in the message transaction.
Notebook lists, permanent search, sharing, catalog publication and Studio exclude attachments.
Request-scoped agent search and image rendering include permanent selected
materials and ready attachments in the current conversation only. Renderer
caches for conversation requests are private to the request.

Accept static PNG, JPEG and WebP. Validate file contents, decoding, dimensions
and frame count before storage; autorotate and normalize to PNG, stripping
metadata. Local PP-OCRv5 extracts searchable text. A visual-only image remains
ready with a page-one locator so the multimodal agent can open or crop it.
Images do not use the PDF parser. Other document formats use their existing
parsers. Original uploaded filename is retained, while image bytes and MIME
type refer to the sanitized PNG. The size limit also applies after sanitizing.

Default attachment limits are 25 MiB per file and **25 MiB combined per
message**, five files per message and twenty per conversation. Images are
limited to 20 million pixels and 8,000 pixels on either side. These limits are
configured with `GUGUTA_CHAT_ATTACHMENT_*` and `GUGUTA_MAX_IMAGE_*` in
`.env.guguta.example`. The browser displays server limits; the server enforces
them, including cumulative upload batches, under user and conversation locks.
Attachments also count against the user's storage quota. The combined message
limit fits the existing 32 MiB reverse-proxy request limit.

The existing reset button deletes the current conversation, then creates a
new one. A migration-owned deletion trigger removes ephemeral material
versions, assets, processing jobs and their derived artifacts, chunks and
vectors in the same transaction as deletion of the association. Claimed jobs
cannot publish after deletion; publication locks sources before jobs.
Permanent source deletion retains its existing lifecycle.

Physical file deletion uses a durable outbox with actor RLS for API cleanup
and worker access for retries. API deletion attempts unlink immediately;
failure retains the outbox record and the worker retries it. Database access
to deleted attachments ends immediately even if storage deletion is deferred.
Authenticated downloads use `Cache-Control: private, no-store`. User notes
explicitly saved from answers keep their existing retention semantics.

Migration 0021 follows the already deployed school-origin migration 0020;
both must be present when deploying from Git. Deploy migrations before the
new worker. Downgrade requires deleting attachments and draining the outbox.

Validation covers image decoding and metadata removal, OCR and pixel/crop
evidence, lexical/vector retrieval, same-user conversation isolation and
cross-user access, streamed and ordinary message binding, quotas under
concurrent uploads, deletion and storage retries, and late worker publication.

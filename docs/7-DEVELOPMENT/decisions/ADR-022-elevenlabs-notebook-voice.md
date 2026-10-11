# ADR-022: ElevenLabs voice with notebook-scoped context

Date: 2026-10-10
Status: Accepted

## Context

Guguță already offers notebook chat, microphone dictation, and a companion with
page-specific context. Real-time spoken conversation should use the configured
ElevenLabs agent while following the current notebook, selected materials, and
visible learning activity.

## Decision

Use the ElevenLabs browser client with a private agent. The authenticated Guguță
API issues a short-lived conversation token; the workspace API key stays on the
server. Existing session authentication, CSRF validation, and notebook access
checks govern voice bootstrap and material retrieval.

Keep a stable Romanian tutor prompt in the agent. Pass `guguta_context` and
`guguta_greeting` per conversation, and send contextual updates when the visible
learning activity changes. Stop microphone capture when the component/page is
closed or its notebook scope changes.

On the homepage, provide the platform's identity, educational purpose, and
available learning tools. With no notebook open, do not retrieve notebook
materials or reuse content from a previously opened notebook.

The `search_notebook_materials` client tool calls the authenticated Guguță API to
retrieve bounded passages from the current notebook's selected sources. This
avoids uploading all notebook content to a shared ElevenLabs knowledge base.
Material excerpts are context data, not agent instructions. The tool can read
only the notebook and materials accessible to the current signed-in user.

The companion voice button starts or stops a conversation directly, with visible
connection state and stop/mute controls. Dictation belongs to the text chat
composer; the two modes must not own the microphone simultaneously. Text chat
retains its existing backend.

Enable ElevenLabs' native `end_call` system tool with its default behavior.
The agent decides when a conversation has concluded; SDK disconnection events
release the microphone and reset the UI. Do not implement farewell-word
detection or a separate conversation-ending policy in the browser.

Conversation animations use calm explanation/listening/thinking poses from the
existing sprite atlas. Small speech motion follows the SDK's output-volume
analyser, without a separate microphone stream or phoneme lip-sync. Existing
drag, quiz-result, and text-chat animations keep their original behavior.

On each voice session, restore playback volume for newly attached audio
elements. LiveKit can recycle detached elements between conversations; teardown
must not leave them at zero volume for the next session. Stop playback through
the SDK's session cleanup and retain cancellation guards for late callbacks.

## Consequences

ElevenLabs receives spoken input and the context/retrieved passages needed for
the user's conversation. Private credentials are not exposed to the browser.
There are no database migrations or changes to other users' notebooks. Deployment
updates only the frontend/API and preserves existing compose overrides, themes,
background workers, and speech services.

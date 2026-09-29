# Adversarial Review Ledger

## ADV-001: Floating and Popup UI Element Interception
- **Threat Vector**: Floating UI elements (Messenger chat docks, call popups, notification panels, friend request toasts, video modals) stealing focus or intercepting synthetic keyboard inputs.
- **Attack / Failure Scenario**:
  1. A chat tab pops up dynamically mid-run while the bot is preparing to comment.
  2. The bot clicks into an input field or assumes focus, sending text meant for public group comments into private chat threads.
  3. Enter key transmits the message to the conversation recipient.
- **Countermeasure**:
  1. Strict scoping: Textbox MUST be a descendant of `loc` (the feed post `div[role="article"]`).
  2. Pre-action sweep: Automatically close any visible chat tabs before commenting via `close_all_chat_windows(page)`.
  3. Runtime DOM verification: Inspect `document.activeElement` immediately after click and right before `page.keyboard.type` / `page.keyboard.press("Enter")`. If inside Messenger or unexpected container, abort immediately, press Escape, and log warning.
- **Status**: MITIGATED & TESTED (Live Playwright verification passed)

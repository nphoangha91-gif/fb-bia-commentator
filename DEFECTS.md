# Defect Ledger

## DEF-001: Auto-commenter hijacking Facebook Messenger chat docks
- **Status**: CLOSED
- **Severity**: HIGH
- **Component**: `comment_workflow_core.py` -> `safe_comment_to_post`
- **Root Cause**:
  Line 262 in `comment_workflow_core.py` used an un-scoped page-level fallback:
  ```python
  if await comment_box.count() == 0:
      comment_box = page.locator('div[role="textbox"][contenteditable="true"]').last
  ```
  On Facebook Desktop, docked Messenger chat tabs render at the bottom-right and sit at the end of the DOM. When a post's comment box was not found immediately, `.last` selected the open Messenger chat input, resulting in marketing comments being typed and sent into private Messenger conversations.
- **Resolution**:
  1. Completely removed un-scoped `.last` fallback. Comment box search is strictly isolated within the post locator `loc`.
  2. Implemented `close_all_chat_windows(page)` to automatically close any floating Messenger chat tabs upon entering groups and before interacting with posts.
  3. Implemented `is_messenger_element(locator)` to verify the comment box element does not belong to Messenger.
  4. Implemented `is_active_element_messenger(page)` to verify that `document.activeElement` is never a Messenger element after focus and before pressing Enter.
- **Verification Evidence**:
  - Spike test `.planning/spikes/test_messenger_defense.py` passed all synthetic and live tests.
  - End-to-end dry run with live cookies successfully executed against group posts with 3 proof screenshots (`proof_comment_g1_p1.png`, `proof_comment_g1_p2.png`, `proof_comment_g1_p3.png`) showing pristine post-only targeting and zero Messenger interaction.
- **Lifecycle**:
  - Identified: 2026-09-25
  - Fixed in: `comment_workflow_core.py`
  - Verified: 2026-09-25 (CLOSED)

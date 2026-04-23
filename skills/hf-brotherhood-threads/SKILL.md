---
name: hf-brotherhood-threads
description: Create Brotherhood-branded Hack Forums threads with required layout structure and human-quality final copy
user-invocable: true
context: full
visibility: exported
owner: hackforums-council
---

# HF Brotherhood Threads

Use this skill when you need a Brotherhood-branded Hack Forums thread draft that preserves the required layout pattern and reads like real human writing.

## Trigger Conditions

- The task is to draft a Brotherhood-style HF thread, not just generic BBCode syntax.
- The output must follow a known branded structure, including required `[css=68]`.
- The thread needs polished body copy, not only a formatting shell.

## Inputs

- Thread topic and intended audience.
- Verified facts, claims, links, and examples that can be defended.
- Media URLs for hero and divider images.
- Any operator constraints (tone, section focus, call to action, length).

## Procedure

1. Start from `references/BROTHERHOOD_THREAD_TEMPLATE.md`.
   Keep the root flow here short and do the full thread build inside the companion template.

2. Preserve the Brotherhood layout contract exactly.
   The draft must include required `[css=68]`, centered headline block, centered hero image block, divider image blocks between sections, large centered section headers, and article-body paragraphs under each section.

3. Fill placeholders with real content.
   Replace all template markers with concrete facts, specific examples, and explicit claims that can be verified.

4. Run `$natural-writing` before finalizing.
   Apply its process and quality rules to remove AI tells, keep voice, keep wording specific, and fact-check every claim.

5. Run the `$natural-writing` self-audit loop as a hard gate.
   Ask "What makes this obviously AI generated?", list remaining tells, revise, and repeat until the answer is "nothing obvious."

6. Return one ready-to-paste HF thread block.
   Keep the final output in MyCode with the required Brotherhood structure intact.

## Verification

- Confirm `[css=68]` is present and wrapped correctly.
- Confirm the thread includes centered title, centered hero image, divider blocks, and centered section headers.
- Confirm all placeholders were replaced with concrete, topic-specific content.
- Confirm `$natural-writing` was applied and the self-audit loop is explicitly completed.
- Confirm no live-posting, API-write, or runtime-change steps were added.

## Output / Handoff

- One complete MyCode thread draft that is ready to paste into HF composer.
- A short assumptions note listing any unresolved facts as `[VERIFY]`.
- Optional next-step note to use `hf-mycode` only for syntax troubleshooting.

## Boundaries

- Do not treat `[css=68]` as optional for this Brotherhood lane.
- Do not expand this skill into runtime code, manifests, or posting automation.
- Do not split a separate writing-quality HF skill in this wave.
- Do not rewrite `hf-mycode`; keep it as the general syntax sibling.

## References

- [BROTHERHOOD_THREAD_TEMPLATE.md](references/BROTHERHOOD_THREAD_TEMPLATE.md)

---
allowed-tools: Read, Glob, Grep, Edit
description: >
  Audit source files for line-length violations and
  reflow to the 70-80 character target band.
---

# Lint: Line-Length Audit and Reflow

Audit source code files for line-length violations and reflow
them into the 70-80 character target band. The user provides a
target as `$ARGUMENTS`, which may be:

- A specific file (e.g., `src/uolcao/dos.F90`)
- A directory (e.g., `src/uolcao/`)
- A glob pattern (e.g., `**/*.f90`, `src/scripts/*.py`)
- Omitted — default to `src/`

Follow these steps precisely.

**Step 1: Identify target files**

Resolve `$ARGUMENTS` into a list of source files. Use Glob to
expand directories and patterns. Include only source files
(`.f90`, `.F90`, `.py`, `.pl`, `.pm`). Skip binary files, swap
files, and build artifacts.

If the target resolves to more than 20 files, list the count
and ask the programmer whether to proceed or narrow the scope.

**Step 2: Scan for violations**

Read each target file and identify lines that violate the
line-length rules:

1. **Over-length** (hard violation): lines exceeding 80
   characters. These MUST be fixed.
2. **Under-filled** (soft violation): lines shorter than 70
   characters where the content could reasonably be reflowed
   to fill closer to 70-80. This applies to:
   - Comment blocks where consecutive short comment lines
     could be merged into fewer, fuller lines.
   - String literals or argument lists that were broken early
     when more content would fit on the line.

   Do NOT flag as under-filled:
   - Lines that are naturally short (e.g., `implicit none`,
     `end if`, `return`, blank lines, single closing
     brackets/parentheses).
   - Lines where filling further would break code logic or
     readability (e.g., one-item-per-line formatting that
     aids clarity).
   - The last line of a reflowed paragraph or comment block
     (it may be a short remainder and that is fine).

**Step 3: Report findings**

Present a summary grouped by file:

```
Line-length audit: N file(s) scanned, M violation(s) found.

--- src/uolcao/dos.F90 ---
  Over-length (K):
    L42  (87 chars): <truncated line preview>
    L108 (83 chars): <truncated line preview>
  Under-filled (J):
    L55-L58: comment block averages 41 chars/line
    L200 (38 chars): argument list could join previous line

--- src/uolcao/kpoints.f90 ---
  No violations found.
```

If no violations are found in any file, say so and stop.

**Step 4: Ask for approval**

Ask the programmer:
"Shall I reflow these files to fix the violations? You can
approve all, select specific files, or skip."

Do NOT proceed without explicit approval.

**Step 5: Apply fixes (only after approval)**

For each approved file, reflow the violating lines:

- **Over-length lines**: wrap at a natural break point
  (space, comma, operator) so that both the original line
  and the continuation fall within 70-80 characters when
  content allows. Use appropriate continuation syntax:
  - Fortran: `&` at end of line, `&` at start of
    continuation (in column 6+ for free-form).
  - Python: use implicit continuation inside brackets, or
    `\` where necessary.
  - Perl: break after an operator or comma.
  - Comments: reflow the paragraph to fill lines toward
    70-80 characters.

- **Under-filled lines**: merge short consecutive comment
  lines or join short argument-list fragments so that each
  line approaches the 70-80 character band. Do not add new
  words, pad with whitespace, or change code meaning.

- **Preserve meaning**: never alter logic, variable names,
  or executable behavior. Only whitespace and line breaks
  should change.

After applying fixes, re-scan the modified file to confirm
no new violations were introduced. Report the result.

**Step 6: Summary**

Report what was changed:

```
Reflow complete:
  src/uolcao/dos.F90: 12 lines reflowed (8 over, 4 under)
  src/uolcao/kpoints.f90: skipped (no approval)
```

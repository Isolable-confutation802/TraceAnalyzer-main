# sub_12208 OLLVM Deflat Report (MCP/IDA)

## MCP connectivity
- Configured MCP server: `ida_pro_mcp` at `http://127.0.0.1:13337/mcp`
- Handshake: OK
- Tool access: OK (`lookup_funcs`, `decompile`, `disasm`, `basic_blocks`, `py_eval`, etc.)

## Target function
- Name: `sub_12208`
- Address: `0x12208`
- IDA reported size: `0x2020` (contains flattened dispatcher + hidden tails)

## Key OLLVM traits found
- Dispatcher table #1:
  - Table: `off_21FB0` (`0x21FB0`)
  - Target formula: `target = qword(off_21FB0[idx]) + 0x14DC1034`
  - Main dispatcher block: `0x132E8`
- State variable:
  - Stored via pointer loaded from stack `var_68`
  - Multiple blocks write 32-bit state constants then jump back to dispatcher
- Anti-analysis/anti-decompile entry split:
  - Fake trap region: `0x14228` (repeated `SUB SP/MOV SP` pattern)
  - Real init path: `0x143BC`
  - Original function boundary hid this tail in IDA default CFG

## Stage-1 deobf patch applied in IDA
- `0x12288`: `CSEL W8, W10, W9, NE` -> `MOV W8, #0xAF`
- `0x122CC`: `BR X9` -> `B 0x143BC`
- `0x1466C`: `BR X9` -> `B 0x136B0` (folded from static global predicate in this sample)
- Function tail merge:
  - `0x14228..0x143BC`
  - `0x143BC..0x14670`

Effect:
- Decompiler now follows the real init region instead of stopping at the first opaque `BR`.
- First-stage control flow is materially clearer (Hex-Rays now recovers argument list and expanded local frame).

## Artifacts generated locally
- Full disasm (paged pull from MCP):
  - `sub_12208_disasm_full.txt`
- One-shot IDA script for repeatable patching/annotation:
  - `sub_12208_ollvm_deflat.py`

## Recommended next pass (stage-2)
- Automate deflat for nested dispatcher around `0x14670` (`off_22580` table family).
- Fold opaque predicates based on static globals `dword_20Cxx`.
- Rebuild merged CFG and re-decompile after each patch batch.

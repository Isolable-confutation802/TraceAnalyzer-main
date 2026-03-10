"""
IDA Python script for first-stage OLLVM deflat on sub_12208.

What it does:
1) Force sub_12208 entry to jump into real init path (0x143BC).
2) Merge hidden tail chunks into sub_12208 function.
3) Decode dispatcher jump table off_21FB0 (+0x14DC1034).
4) Add basic comments for dispatcher and anti-analysis region.
5) Export jump table mapping to JSON.

Tested with IDA + keystone installed.
"""

import json
from pathlib import Path

import ida_auto
import ida_bytes
import ida_funcs
import ida_kernwin
import ida_lines
import ida_name
import ida_ua

from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN


FUNC_START = 0x12208
REAL_INIT = 0x143BC
FAKE_TRAP = 0x14228
TAIL_1_START = 0x14228
TAIL_1_END = 0x143BC
TAIL_2_START = 0x143BC
TAIL_2_END = 0x14670

ENTRY_PATCH_1_EA = 0x12288
ENTRY_PATCH_2_EA = 0x122CC

JT_BASE = 0x21FB0
JT_ADD = 0x14DC1034
JT_COUNT = 0xC0


def asm_patch(ea: int, asm: str) -> bytes:
    ks = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)
    encoding, _ = ks.asm(asm, addr=ea)
    data = bytes(encoding)
    for i, b in enumerate(data):
        ida_bytes.patch_byte(ea + i, b)
    ida_ua.create_insn(ea)
    return data


def add_tail_chunk(func, start: int, end: int) -> bool:
    if start >= end:
        return False
    return bool(ida_funcs.append_func_tail(func, start, end))


def decode_jump_table():
    rows = []
    for i in range(JT_COUNT):
        ea = JT_BASE + i * 8
        raw = ida_bytes.get_qword(ea)
        target = (raw + JT_ADD) & 0xFFFFFFFFFFFFFFFF
        rows.append(
            {
                "index": i,
                "table_ea": hex(ea),
                "raw_qword": hex(raw),
                "target": hex(target),
            }
        )
    return rows


def mark_comments():
    ida_bytes.set_cmt(ENTRY_PATCH_1_EA, "deflat patch: force init index to 0xAF", 0)
    ida_bytes.set_cmt(ENTRY_PATCH_2_EA, "deflat patch: jump to real init block 0x143BC", 0)
    ida_bytes.set_cmt(0x132E8, "dispatcher #1 (state machine router)", 0)
    ida_bytes.set_cmt(FAKE_TRAP, "anti-analysis trap region", 0)
    ida_name.set_name(0x132E8, "sub_12208_dispatcher", ida_name.SN_FORCE)
    ida_name.set_name(REAL_INIT, "sub_12208_real_init", ida_name.SN_FORCE)


def export_mapping(rows):
    db_path = ida_kernwin.get_path(ida_kernwin.PATH_TYPE_IDB)
    out_path = Path(db_path).with_suffix(".sub_12208_jumptable.json")
    out_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return out_path


def main():
    func = ida_funcs.get_func(FUNC_START)
    if not func:
        raise RuntimeError(f"Function not found at {FUNC_START:#x}")

    # First-stage entry deflat patch.
    p1 = asm_patch(ENTRY_PATCH_1_EA, "mov w8, #0xaf")
    p2 = asm_patch(ENTRY_PATCH_2_EA, f"b {REAL_INIT:#x}")

    # Merge hidden function chunks.
    ok1 = add_tail_chunk(func, TAIL_1_START, TAIL_1_END)
    ok2 = add_tail_chunk(func, TAIL_2_START, TAIL_2_END)

    mark_comments()
    rows = decode_jump_table()
    out_file = export_mapping(rows)

    ida_auto.auto_wait()

    msg = (
        "sub_12208 deflat stage-1 done\\n"
        f"  patch {ENTRY_PATCH_1_EA:#x}: {p1.hex()}\\n"
        f"  patch {ENTRY_PATCH_2_EA:#x}: {p2.hex()}\\n"
        f"  append tail {TAIL_1_START:#x}-{TAIL_1_END:#x}: {ok1}\\n"
        f"  append tail {TAIL_2_START:#x}-{TAIL_2_END:#x}: {ok2}\\n"
        f"  jumptable dump: {out_file}\\n"
    )
    print(msg)
    ida_kernwin.msg(msg)


if __name__ == "__main__":
    main()

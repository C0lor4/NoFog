"""Assemble the guest against the Horizon 6d765e0 wire ABI. Requires WABT."""

import argparse
from pathlib import Path
import struct
import subprocess
import tempfile
import tomllib


def u32(number):
    return struct.pack("<I", number)


def string(text):
    data = text.encode("utf-8")
    return u32(len(data)) + data


def assemble(assembler, output):
    manifest = Path(__file__).with_name("horizon-mod.toml")
    mod_id = tomllib.loads(manifest.read_text(encoding="utf-8"))["id"]
    names = ["client_tick_post", "setting_changed", "input_key", "mouse_button_post",
             "camera_submersion"]
    settings = ["active", "water", "lava", "powder_snow"]
    # Names and records follow the pinned SDK's wire_guest_generated.rs and
    # horizon-mod-vocab/src/{client/key_mapping.rs,content/mod_settings.rs}.
    values = {
        "listeners": u32(len(names)) + b"".join(string(name) + u32(0) + bytes([0]) for name in names),
        "register_key": (
            string("toggle") + string(f"key.{mod_id}.toggle") + string("key.keyboard.g")
            + u32(0) + string("") + u32(1)
        ),
        "owner": string(mod_id),
        "binding": string(mod_id) + string("toggle"),
        "on": string(mod_id) + string("active") + string("true"),
        "off": string(mod_id) + string("active") + string("false"),
    }
    for setting in settings:
        label = f"{mod_id}.setting.{setting}"
        tooltip = b"\x01" + string(label + ".tooltip") if setting == "active" else b"\x00"
        values[setting] = string(setting)
        values["register_" + setting] = (
            string(setting) + string(label) + tooltip + u32(0) + bytes([1])
        )
    payload = bytearray()
    accessors = []
    for name, data in values.items():
        pos = len(payload)
        payload.extend(data)
        accessors.append(
            f"(func ${name} (result i32 i32) "
            f"(i32.add (global.get $base) (i32.const {pos})) (i32.const {len(data)}))"
        )
    if len(payload) > 1024:
        raise ValueError("Static strings overlap call frames")
    assembly = Path(__file__).with_name(f"{mod_id}.wat.in").read_text(encoding="utf-8")
    assembly = assembly.replace("{{accessors}}", "\n  ".join(accessors))
    assembly = assembly.replace("{{payload}}", "".join(f"\\{byte:02x}" for byte in payload))
    with tempfile.TemporaryDirectory() as work:
        source = Path(work) / f"{mod_id}.wat"
        source.write_text(assembly, encoding="utf-8")
        subprocess.run([*assembler, str(source), "--enable-annotations", "-o", str(output)], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assembler", nargs="+", default=["wat2wasm"],
                        help="WABT command, e.g. node path/to/wabt/bin/wat2wasm")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("mod.wasm"))
    args = parser.parse_args()
    assemble(args.assembler, args.output)

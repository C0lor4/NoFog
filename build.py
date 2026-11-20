"""Assemble the guest against the Horizon f00125f named-call ABI. Requires WABT."""

import argparse
from pathlib import Path
import struct
import subprocess
import tempfile
import tomllib


# Generated wire_guest_generated.rs provides each import signature. The SDK's
# call_layouts() folds the access checks and the layouts of every reached type
# into the additional compatibility hashes below.
IMPORTS = [
    ("Host::on", "76eb174b45940e2d", 0x0d47f339e9b8e528),
    ("Host::set_setting", "914eecee06696500", 0x0e1a035c190e652f),
    ("ClientHost::consume_click", "5a9ba86f9c663c58", 0xb7dd7eb2615888ad),
    ("ClientHost::playing", "59448d2d5e8409d2", 0x077f303fd818e484),
    ("ClientHost::setting_bool", "2fa32581056a8165", 0x9b77c8d62b05efb6),
    ("Registrar::register_key_mapping", "6e28ee6aa324b133", 0x06a5f040eadebda2),
    ("Registrar::register_setting", "5d8b90fbcef4eaac", 0xf9ce422389f57b24),
]
EXPORTS = [
    ("Hooks::subscribed", 0x6e6a0f5e2ee50088),
    ("Hooks::register", 0x119bb40d046630ee),
    ("Hooks::setting_changed", 0xb139d646bb2e33b8),
    ("Hooks::mouse_button_post", 0xdc0af3fbc6711a5f),
    ("Hooks::input_key", 0xd478689c5562b65b),
    ("Hooks::camera_submersion", 0x104b3d790d61fd80),
    ("Hooks::client_tick_post", 0x8509eefe42cb27d1),
]


def hook_id(name):
    # horizon-mod-api-gen/src/wire/names.rs: export_id
    hash_value = 0xcbf29ce484222325
    for byte in name.encode("utf-8"):
        hash_value = (hash_value ^ byte) * 0x100000001b3 & 0xffffffffffffffff
    return hash_value & 0x3fffffff


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
    calls = [(name, value, False) for name, _, value in IMPORTS]
    calls.extend((name, value, True) for name, value in EXPORTS)
    values["calls"] = u32(len(calls)) + b"".join(
        string(name) + struct.pack("<QB", value, exported)
        for name, value, exported in calls
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
    if len(payload) > 2048:
        raise ValueError("Static strings overlap call frames")
    assembly = Path(__file__).with_name(f"{mod_id}.wat.in").read_text(encoding="utf-8")
    # Keeping the named import and its wrapper together gives each host call its
    # own checked signature without dispatching through positional host IDs.
    imports = []
    wrappers = []
    for name, signature, _ in IMPORTS:
        method = name.split("::")[1]
        imports.append(
            f'(import "horizon" "{name}#{signature}" '
            f'(func $import_{method} (param i32 i32 i32 i32) (result i32)))'
        )
        wrappers.append(
            f"(func $host_{method} (param $ptr i32) (param $len i32) (result i32) "
            f"(call $check_size (call $import_{method} (local.get $ptr) "
            f"(local.get $len) (call $reply) (i32.const 20))))"
        )
    assembly = assembly.replace("{{imports}}", "\n  ".join(imports))
    assembly = assembly.replace("{{host_calls}}", "\n  ".join(wrappers))
    for name, _ in EXPORTS:
        marker = "{{hook_" + name.split("::")[1] + "}}"
        assembly = assembly.replace(marker, str(hook_id(name)))
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

//! Horizon SDK implementation for `cargo horizon-mod build --wasm`.
//! The distributed binary is assembled from `nofog.wat.in` by `build.py`.
use mod_api::client::fog::FogType;
use mod_api::{
    CameraSubmersionEvent, ClientHost, ClientTickPostEvent, Hooks, InputKeyEvent, KeyAction,
    KeyConflictContext, KeyRegistration, MouseButtonPostEvent, Registrar, RegistrationContext,
    SettingChangedEvent, SettingSpec,
};
use std::sync::atomic::{AtomicU8, Ordering};

const ID: &str = "nofog";
const KEY: &str = "toggle";
const ACTIVE: u8 = 1;
const WATER: u8 = 2;
const LAVA: u8 = 4;
const POWDER_SNOW: u8 = 8;
const LOADED: u8 = 16;
const SETTINGS: [(&str, &str, u8); 4] = [
    ("active", "nofog.setting.active", ACTIVE),
    ("water", "nofog.setting.water", WATER),
    ("lava", "nofog.setting.lava", LAVA),
    (
        "powder_snow",
        "nofog.setting.powder_snow",
        POWDER_SNOW,
    ),
];

#[derive(Default)]
struct NoFog {
    // Avoid reading the settings for every rendered frame. A host call can
    // fire a nested hook, so keep no lock while asking for these values.
    flags: AtomicU8,
}

impl NoFog {
    fn refresh(&self, host: &dyn ClientHost) -> u8 {
        let mut flags = LOADED;
        for (key, _, bit) in SETTINGS {
            if host.setting_bool(key).unwrap_or(true) {
                flags |= bit;
            }
        }
        self.flags.store(flags, Ordering::Relaxed);
        flags
    }

    fn settings(&self, host: &dyn ClientHost) -> u8 {
        let flags = self.flags.load(Ordering::Relaxed);
        if flags & LOADED == 0 {
            self.refresh(host)
        } else {
            flags
        }
    }

    fn input(&self, host: &mut dyn ClientHost, pressed: bool) {
        // Consume the mapping on every input event, including OS repeats.
        // Only a real press of the player's registered binding flips it.
        if host.consume_click(ID, KEY) && pressed && host.on(ID) && host.playing() {
            let active = host.setting_bool("active").unwrap_or(true);
            host.set_setting(ID, "active", if active { "false" } else { "true" });
            self.refresh(host);
        }
    }
}

#[mod_api::horizon_mod]
impl Hooks for NoFog {
    fn register(&self, registrar: &mut dyn Registrar, _: &RegistrationContext) {
        registrar.register_key_mapping(
            KeyRegistration::new(KEY, "key.keyboard.g")
                .label("key.nofog.toggle")
                .context(KeyConflictContext::InGame),
        );
        for (key, label, _) in SETTINGS {
            let mut spec = SettingSpec::toggle(key, label, true);
            if key == "active" {
                spec = spec.tooltip("nofog.setting.active.tooltip");
            }
            registrar
                .register_setting(spec)
                .expect("nofog settings must be registered once");
        }
    }

    fn client_tick_post(&self, host: &mut dyn ClientHost, _: &mut ClientTickPostEvent) {
        self.settings(host);
    }

    fn setting_changed(&self, host: &mut dyn ClientHost, _: &mut SettingChangedEvent<'_>) {
        self.refresh(host);
    }

    fn input_key(&self, host: &mut dyn ClientHost, event: &mut InputKeyEvent<'_>) {
        self.input(host, event.action == KeyAction::Press);
    }

    fn mouse_button_post(&self, host: &mut dyn ClientHost, event: &mut MouseButtonPostEvent) {
        self.input(host, event.pressed);
    }

    fn camera_submersion(&self, host: &dyn ClientHost, event: &mut CameraSubmersionEvent<'_>) {
        let flags = self.settings(host);
        let bit = match *event.fog_type {
            FogType::Water => WATER,
            FogType::Lava => LAVA,
            FogType::PowderSnow => POWDER_SNOW,
            FogType::Atmospheric => return,
        };
        if flags & ACTIVE != 0 && flags & bit != 0 && host.on(ID) {
            *event.fog_type = FogType::Atmospheric;
        }
    }
}

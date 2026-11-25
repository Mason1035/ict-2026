"""Read-only real SD replay; run using platform_backend/.venv/bin/python."""
from geohazard_platform.sd_mqtt_replay import main

if __name__ == "__main__":
    raise SystemExit(main())

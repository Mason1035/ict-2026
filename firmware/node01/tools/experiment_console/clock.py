from datetime import datetime, timedelta, timezone
import re
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class HostClock:
    def __init__(self, timezone_name=None, utc_offset=None, confirmed=False):
        if timezone_name and utc_offset:
            raise ValueError('时区与固定UTC偏移只能选一个')
        self.kind = 'WINDOWS_SYSTEM_LOCAL'
        self.zone = None
        self.key = 'system-local'
        if timezone_name:
            try:
                self.zone = ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError as exc:
                raise ValueError('IANA时区不可用；安装独立venv的tzdata或显式使用 --utc-offset=+08:00') from exc
            self.kind, self.key = 'EXPLICIT_IANA', timezone_name
        elif utc_offset:
            match = re.fullmatch(r'([+-])(\d{2}):(\d{2})', utc_offset)
            if not match or int(match[2]) > 14 or int(match[3]) > 59 or (int(match[2]) == 14 and int(match[3])):
                raise ValueError('UTC偏移必须为±HH:MM，范围±14:00')
            minutes = (int(match[2]) * 60 + int(match[3])) * (1 if match[1] == '+' else -1)
            self.zone = timezone(timedelta(minutes=minutes))
            self.kind, self.key = 'EXPLICIT_FIXED_OFFSET_NO_DST', utc_offset
        self.confirmed = confirmed

    def sample(self):
        utc = datetime.now(timezone.utc)
        return self.at(utc, time.monotonic_ns())

    def at(self, utc, monotonic_ns):
        if utc.tzinfo is None:
            raise ValueError('时间必须有UTC偏移')
        local = utc.astimezone(self.zone) if self.zone is not None else utc.astimezone()
        offset = local.strftime('%z')
        offset = offset[:3] + ':' + offset[3:]
        return {'iso8601': local.isoformat(timespec='microseconds'),
                'utc_iso8601': utc.astimezone(timezone.utc).isoformat(timespec='microseconds'),
                'monotonic_ns': monotonic_ns, 'utc_offset': offset,
                'timezone_kind': self.kind, 'timezone_key': self.key,
                'timezone_display': local.tzname(), 'operator_clock_confirmed': self.confirmed}


class ClockGuard:
    def __init__(self):
        self.previous = None
        self.issues = []

    def observe(self, sample):
        new = []
        if self.previous and sample['monotonic_ns'] >= self.previous['monotonic_ns']:
            wall = (datetime.fromisoformat(sample['utc_iso8601']) -
                    datetime.fromisoformat(self.previous['utc_iso8601'])).total_seconds()
            monotonic = (sample['monotonic_ns'] - self.previous['monotonic_ns']) / 1e9
            if abs(wall - monotonic) > 2.0:
                new.append('HOST_CLOCK_JUMP')
            if sample['timezone_key'] != self.previous['timezone_key'] or (
                    sample['timezone_kind'] == 'WINDOWS_SYSTEM_LOCAL' and
                    sample['utc_offset'] != self.previous['utc_offset']):
                new.append('HOST_TIMEZONE_OR_SYSTEM_OFFSET_CHANGED')
        # A reader timestamp may be processed after a concurrent TX timestamp.
        # Do not mistake that scheduling order for the OS monotonic clock reversing.
        if not self.previous or sample['monotonic_ns'] >= self.previous['monotonic_ns']:
            self.previous = sample
        for issue in new:
            if issue not in self.issues:
                self.issues.append(issue)
        return new

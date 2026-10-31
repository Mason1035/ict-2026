import argparse
import asyncio
from collections import deque
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.lexers import Lexer
from serial.tools import list_ports

from .clock import HostClock
from .core import Engine, Journal
from .transport import Receiver, open_port

PROJECT = Path(__file__).resolve().parents[2]
REPOSITORY = PROJECT.parents[1]
DEFAULT_ROOT = REPOSITORY / 'docs/test_records/NODE-01/sandbox-experiment-archive/console-runs'


def default_manifest():
    latest = REPOSITORY / 'docs/test_records/NODE-01/round-15-sandbox-mode/LATEST.json'
    return Path(json.loads(latest.read_text(encoding='utf-8-sig'))['manifest'])


def expected_identity(path):
    manifest = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if manifest.get('mode') != 'SANDBOX_EXPERIMENT_CAPTURE':
        raise ValueError('Manifest不是沙盘采集模式')
    root = Path(manifest['build_directory']).resolve()
    for entry in manifest['files'].values():
        file = (root / entry['relative_path']).resolve()
        if not file.is_relative_to(root) or file.stat().st_size != entry['bytes']:
            raise ValueError('候选产物路径/大小不匹配')
        with file.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != entry['sha256']:
            raise ValueError('候选产物SHA不匹配：' + str(file))
    return manifest['files']['zhishao_node01.elf']['sha256']


class MessageLexer(Lexer):
    def lex_document(self, document):
        def line_tokens(index):
            text = document.lines[index]
            style = 'fg:ansired bold' if text.startswith(('[ESP错误]','[本机错误]','[致命错误]','[退出警告]')) else 'fg:ansiyellow' if text.startswith('[ESP告警]') else 'fg:ansicyan' if text.startswith('[PC发送]') else 'fg:ansigreen' if text.startswith('[ESP回复]') else ''
            return [(style, text)]
        return line_tokens


class ConsoleUI:
    """Separate fixed input buffer; RX never prints over the editing area."""
    def __init__(self, engine, writer, input=None, output=None, port_provider=None):
        self.engine, self.writer = engine, writer
        self.port_provider = port_provider or list_ports.comports
        self.rows = deque()
        self.characters = 0
        self.quit_warning = False
        self.log = TextArea(read_only=True, scrollbar=True, focusable=False, wrap_lines=True, lexer=MessageLexer())
        self.input = TextArea(height=1, prompt='NODE-01 > ', multiline=False,
                              accept_handler=self.accept)
        self.key_bindings = KeyBindings()
        for key in ['c-c', 'c-d']:
            self.key_bindings.add(key)(self.quit_key)
        self.app = Application(layout=Layout(HSplit([
            Window(FormattedTextControl(self.header), height=4), self.log,
            Window(height=1, char='─'), self.input,
            Window(FormattedTextControl(self.footer), height=2)]), focused_element=self.input),
            key_bindings=self.key_bindings, full_screen=True, mouse_support=False,
            input=input, output=output, refresh_interval=0.2)

    def header(self):
        value = self.engine.snapshot()
        clock = self.engine.clock.sample()
        pending = value['pending']['command'] if value['pending'] else '无'
        return [('bold', 'NODE-01 沙盘实验控制台' + (' [TEST_ONLY 模拟]' if value['test_only'] else '') + '\n'),
                ('', f"串口 {value['port']} @ {value['baud']} | 连接 {value['connection_status']} | 设备进度 {value['device_progress_state']} | 实验 {value['experiment_result']} | 待确认 {pending}\n"),
                ('', f"电脑时间 {clock['iso8601']} {clock['timezone_kind']} | {'精简' if not self.engine.verbose else '详细'} | 固件 {value['firmware_identity']}\n"),
                ('fg:ansiyellow', 'UNCALIBRATED / INTEGRATION_NOT_READY | raw: ' + str(self.engine.journal.directory / 'serial.bin'))]

    def footer(self):
        value = self.engine.snapshot()
        last = value['recent_warnings'][-1] if value['recent_warnings'] else ':help 帮助 | :verbose on/off | :status 本机状态 | :ports | :quit'
        terminal = value['last_device_terminal']
        if terminal and terminal['result'] == 'FAILED':
            failed_checks = ','.join(key+'='+str(val) for key,val in terminal['validation'].items() if val == '0')
            last = '设备明确失败终态 FAILED | ' + str(terminal['stop_reason']) + ' | ' + failed_checks + ' | 连接 ' + value['connection_status'] + '；原文/时间保留在session.json'
        return [('fg:ansired' if self.engine.errors else '', last + '\n'),
                ('', f'正常诊断屏幕折叠 {self.engine.suppressed} 行；完整RX独立落盘。CSV_VERIFIED不是结束；退出不自动STOP/RESET。')]

    def append(self, text):
        value = text[:1200]
        self.rows.append(value)
        self.characters += len(value) + 1
        while len(self.rows) > 200 or self.characters > 65536:
            self.characters -= len(self.rows.popleft()) + 1
        content = '\n'.join(self.rows)
        self.log.buffer.set_document(Document(content, len(content)), bypass_readonly=True)

    def accept(self, buffer: Buffer):
        self.app.create_background_task(self.command(buffer.text))
        return False

    def quit_key(self, event):
        self.app.create_background_task(self.quit(False))

    async def quit(self, confirmed):
        if not confirmed and self.engine.state != 'FINALIZED' and not self.quit_warning:
            self.quit_warning = True
            observed = self.engine.snapshot()['last_device_terminal']
            detail = '已观察到明确失败终态，保留FAILED，不能当成功取卡依据' if observed and observed['result'] == 'FAILED' else '未确认完整终态'
            self.append('[退出警告] ' + detail + '；关闭控制台不等于EXP STOP，也不保证CSV收尾。再次Ctrl+C或 :quit confirm 才退出。')
            return
        self.app.exit(result=2 if self.engine.fatal else 0)

    async def command(self, text):
        try:
            if text.startswith(':'):
                if text == ':help':
                    self.append('[本机帮助] :status/:ports/:verbose on|off/:quit；设备用EXP HELP/STATUS/START [30..300]/STOP。先STATUS确认READY，等BEGIN后STOP；一次上电一场。')
                elif text == ':status':
                    status = self.engine.snapshot()
                    self.append('[本机状态] ' + json.dumps({k: status[k] for k in ['state', 'connection_status', 'device_progress_state', 'experiment_result', 'last_device_terminal', 'firmware_identity', 'clock_confirmed', 'clock_issues', 'parse_issues', 'fatal']}, ensure_ascii=False))
                    self.append('[日志目录] ' + str(self.engine.journal.directory))
                elif text in [':verbose on', ':verbose off']:
                    with self.engine.lock:
                        self.engine.verbose = text.endswith('on')
                        self.engine.journal.event('LOCAL_VERBOSE', self.engine.clock.sample(), enabled=self.engine.verbose)
                    self.append('[本机显示] ' + ('详细' if self.engine.verbose else '精简') + '，原始记录始终不变')
                elif text == ':ports':
                    ports = await asyncio.to_thread(self.port_provider)
                    self.append('[本机端口] ' + ('; '.join(f'{p.device} {p.description}' for p in ports) or '未发现；未自动连接'))
                elif text in [':quit', ':quit confirm']:
                    await self.quit(text.endswith('confirm'))
                else:
                    self.append('[本机拒绝] 不支持此本地命令；未写串口')
            elif text.strip():
                self.quit_warning = False
                await asyncio.to_thread(self.engine.send, text, self.writer)
        except Exception as error:
            # Never echo arbitrary invalid input: it could contain a pasted secret.
            self.append('[本机拒绝/错误] ' + str(error))
        self.app.invalidate()

    async def refresh(self):
        while True:
            self.engine.tick()
            for _ in range(64):
                try:
                    item = self.engine.messages.get_nowait()
                except __import__('queue').Empty:
                    break
                origin = 'ESP错误' if item['critical'] and item['origin']=='ESP回复' else item['origin']
                if item.get('severity') == 'WARNING' and origin == 'ESP回复':
                    origin = 'ESP告警'
                self.append(f"[{origin}] " + item['text'])
            if self.engine.fatal:
                self.append('[致命错误] 证据不完整：' + self.engine.fatal + '；未自动STOP，设备可能仍在采集。')
                self.app.exit(result=2)
                return
            self.app.invalidate()
            await asyncio.sleep(0.1)

    async def run(self):
        refresh = asyncio.create_task(self.refresh())
        try:
            return await self.app.run_async()
        finally:
            refresh.cancel()
            await asyncio.gather(refresh, return_exceptions=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='NODE-01 Windows实验控制台；打开后不自动START/STOP/RESET')
    parser.add_argument('--port', default='COM7')
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--list-ports', action='store_true')
    zone = parser.add_mutually_exclusive_group()
    zone.add_argument('--timezone')
    zone.add_argument('--utc-offset')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args(argv)
    if args.list_ports:
        for port in list_ports.comports():
            print(port.device, port.description)
        return 0
    if not re.fullmatch(r'COM[1-9]\d*', args.port, re.I) or not 1200 <= args.baud <= 2000000:
        parser.error('Windows端口须为COM数字；波特率1200–2000000')
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error('当前不是可编辑交互终端；请在Windows Terminal/PowerShell 7运行。--list-ports、归档dry-run可在非交互环境使用；未连接串口。')
    clock = HostClock(args.timezone, args.utc_offset)
    expected = expected_identity(args.manifest or default_manifest())
    print('电脑实际时间/时区：', json.dumps(clock.sample(), ensure_ascii=False))
    print('核对电脑时钟后输入 YES；若不可信输入 UNKNOWN（将禁止精确日期归档）；其它输入退出。')
    choice = input('时间确认 > ').strip().upper()
    if choice not in ['YES', 'UNKNOWN']:
        return 0
    clock.confirmed = choice == 'YES'
    journal = Journal(args.output_dir, clock, args.port, args.baud)
    engine = Engine(journal, clock, expected)
    receiver = None
    try:
        device = open_port(args.port, args.baud)
        receiver = Receiver(device, engine)
        receiver.start()
        result = asyncio.run(ConsoleUI(engine, device.write).run())
    except Exception as error:
        engine.disconnected(error)
        print('原始异常：', repr(error), file=sys.stderr)
        result = 2
    finally:
        try:
            if receiver:
                receiver.stop()
        except Exception as error:
            engine.disconnected(error)
            print('串口关闭异常：', repr(error), file=sys.stderr)
            result = 2
        finally:
            engine.close()
    print('日志目录：', journal.directory)
    print('退出不会自动STOP/RESET；HOST_FILES_NOT_VERIFIED，未标定，INTEGRATION_NOT_READY。')
    if engine.fatal:
        print('证据保存失败原始异常：', engine.fatal, file=sys.stderr)
        return 2
    return result


if __name__ == '__main__':
    raise SystemExit(main())

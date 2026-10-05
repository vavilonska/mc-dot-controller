"""Owner launch and credential-free model queue CLI."""
import argparse
import getpass
import json
from pathlib import Path
import sys

from .controller import Resident, safe_reason
from .ipc import QueueClient
from .transport import Bridge, BridgeError


def choose_existing_token_file():
    """Optional owner-operated handoff; no paths searched and no bytes read here."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
        window = tk.Tk()
        window.withdraw()
        try:
            selected = filedialog.askopenfilename(
                title='Select the existing MineClient Bridge token for this session',
                filetypes=[('Token files', '*.token'), ('All files', '*')])
            if not selected:
                raise ValueError('owner_cancelled_token_selection')
            accepted = messagebox.askyesno(
                'Use existing bridge token for this session?',
                'Use the selected file to authenticate this controller to the local Minecraft bridge? '
                'The token stays in memory and is not copied or saved.')
            if not accepted:
                raise ValueError('owner_cancelled_token_selection')
            return Path(selected)
        finally:
            window.destroy()
    except ValueError:
        raise
    except Exception:
        raise ValueError('file_picker_unavailable_use_hidden_prompt_or_owner_selected_token_file') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue', required=True, help='Shared workspace mailbox directory; not /tmp')
    commands = parser.add_subparsers(dest='command', required=True)
    start = commands.add_parser('start', help='Owner runs this in the actual Java desktop namespace')
    start.add_argument('--base-url', required=True, help='Freshly verified numeric loopback URL; no port discovery')
    credentials = start.add_mutually_exclusive_group()
    credentials.add_argument('--token-file', type=Path, help='Optional private file explicitly selected by the owner; never copied')
    credentials.add_argument('--choose-token-file', action='store_true', help='Owner selects and confirms an existing private token file in a desktop dialog')
    submit = commands.add_parser('submit', help='Send JSON command without HTTP access or a token')
    submit.add_argument('--json', required=True)
    submit.add_argument('--request-id')
    submit.add_argument('--wait', type=float, default=0)
    result = commands.add_parser('result')
    result.add_argument('request_id')
    result.add_argument('--wait', type=float, default=0)
    commands.add_parser('status')
    args = parser.parse_args()
    try:
        if args.command == 'start':
            if args.choose_token_file:
                args.token_file = choose_existing_token_file()
            if args.token_file:
                # This option is for the owner selecting their existing credential.
                # No discovery, environment lookup, copy, save, or token generation.
                with args.token_file.open('r') as stream:
                    token = stream.read(4097).strip()
            else:
                if not sys.stdin.isatty():
                    raise ValueError('start_requires_owner_terminal_for_hidden_bearer_prompt')
                token = getpass.getpass('Existing bridge bearer (hidden; kept only in memory): ')
            bridge = Bridge(args.base_url, token)
            del token
            print('Controller starting; Ctrl-C releases inputs and leaves Minecraft connected.', flush=True)
            Resident(bridge, args.queue).serve()
            return
        client = QueueClient(args.queue)
        if args.command == 'submit':
            body = json.loads(args.json)
            if not isinstance(body, dict):
                raise ValueError('command_requires_json_object')
            request_id = client.submit(body, args.request_id)
            output = client.wait(request_id, args.wait) if args.wait else {'request_id': request_id, 'status': 'queued'}
        elif args.command == 'result':
            output = client.wait(args.request_id, args.wait) if args.wait else client.result(args.request_id)
        else:
            output = client.session()
        print(json.dumps(output, ensure_ascii=False, allow_nan=False, indent=2))
    except (BridgeError, ValueError, OSError, KeyError, TypeError) as exc:
        # Avoid leaking file contents/paths, URLs, tokens, or raw server data in tracebacks.
        print(json.dumps({'status': 'failed', 'reason': safe_reason(exc)}))
        return 1


if __name__ == '__main__':
    sys.exit(main())

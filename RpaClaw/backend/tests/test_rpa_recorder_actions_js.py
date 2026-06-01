import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
ACTIONS_JS_PATH = REPO_ROOT / "RpaClaw" / "backend" / "rpa" / "vendor" / "playwright_recorder_actions.js"


def _run_actions_probe(scenario: str) -> dict:
    if not shutil.which("node"):
        pytest.skip("node is required to validate recorder action JavaScript")

    probe = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        function makeElement(options = {{}}) {{
          const attributes = options.attributes || {{}};
          const element = {{
            nodeType: 1,
            nodeName: options.nodeName || options.tagName || 'BUTTON',
            tagName: options.tagName || options.nodeName || 'BUTTON',
            className: options.className || '',
            textContent: options.textContent || '',
            value: options.value || '',
            type: options.type || '',
            isContentEditable: Boolean(options.isContentEditable),
            parentElement: options.parentElement || null,
            children: options.children || [],
            contains(other) {{
              return other === this || this.children.includes(other);
            }},
            closest(selector) {{
              if (selector === 'button, a, [role="button"], [role="link"]') {{
                let cur = this;
                while (cur) {{
                  const role = (cur.getAttribute && cur.getAttribute('role')) || '';
                  if (cur.nodeName === 'BUTTON' || cur.nodeName === 'A' || role === 'button' || role === 'link') {{
                    return cur;
                  }}
                  cur = cur.parentElement;
                }}
              }}
              return null;
            }},
            getAttribute(name) {{
              return Object.prototype.hasOwnProperty.call(attributes, name) ? attributes[name] : null;
            }},
          }};
          for (const child of element.children) child.parentElement = element;
          return element;
        }}

        const listeners = {{}};
        const emitted = [];
        const context = {{
          console,
          Node: {{ ELEMENT_NODE: 1 }},
          navigator: {{ platform: 'Win32' }},
          setTimeout,
          clearTimeout,
          document: {{
            addEventListener(type, handler) {{ listeners[type] = handler; }},
            removeEventListener() {{}},
          }},
        }};
        context.globalThis = context;

        vm.createContext(context);
        vm.runInContext(fs.readFileSync({json.dumps(str(ACTIONS_JS_PATH))}, 'utf8'), context);

        (async () => {{
        try {{
          const scenario = {json.dumps(scenario)};
          context.__rpaPlaywrightActions.install({{
            document: context.document,
            isPaused: () => false,
            retarget: node => node,
            emitAction: (action, target, payload) => emitted.push({{
              action,
              targetName: target.textContent || '',
              targetNodeName: target.nodeName,
              payload: payload || {{}},
            }}),
          }});

          if (scenario === 'inner-hover-target') {{
            const icon = makeElement({{ nodeName: 'I', tagName: 'I', textContent: 'arrow' }});
            const span = makeElement({{ nodeName: 'SPAN', tagName: 'SPAN', textContent: 'Download', children: [icon] }});
            const button = makeElement({{
              nodeName: 'BUTTON',
              tagName: 'BUTTON',
              textContent: 'Download',
              attributes: {{ role: 'button', 'aria-haspopup': 'list' }},
              children: [span],
            }});
            span.parentElement = button;
            icon.parentElement = span;
            listeners.mouseover({{ isTrusted: true, target: icon }});
          }}

          if (scenario === 'ctrl-v-uppercase-does-not-emit-press') {{
            const input = makeElement({{ nodeName: 'INPUT', tagName: 'INPUT', type: 'text' }});
            listeners.keydown({{
              isTrusted: true,
              target: input,
              key: 'V',
              code: 'KeyV',
              ctrlKey: true,
              altKey: false,
              metaKey: false,
              shiftKey: false,
            }});
          }}

          if (scenario === 'paste-on-input-emits-fill') {{
            const input = makeElement({{
              nodeName: 'INPUT',
              tagName: 'INPUT',
              type: 'text',
              value: 'test1',
            }});
            listeners.paste({{ isTrusted: true, target: input }});
            await new Promise(resolve => setTimeout(resolve, 5));
          }}

          process.stdout.write(JSON.stringify({{ ok: true, emitted }}));
        }} catch (error) {{
          process.stdout.write(JSON.stringify({{
            ok: false,
            name: error.name,
            message: error.message,
            stack: String(error.stack || ''),
          }}));
          process.exitCode = 1;
        }}
        }})();
        """
    )
    completed = subprocess.run(
        ["node", "-e", probe],
        check=False,
        text=True,
        capture_output=True,
    )
    output = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
    assert output, completed.stderr
    payload = json.loads(output)
    assert completed.returncode == 0, payload
    assert payload["ok"] is True
    return payload


def test_hover_on_inner_icon_targets_outer_button():
    payload = _run_actions_probe("inner-hover-target")

    event = payload["emitted"][0]
    assert event["action"] == "hover"
    assert event["targetNodeName"] == "BUTTON"
    assert event["targetName"] == "Download"


def test_ctrl_v_uppercase_does_not_emit_press_action():
    payload = _run_actions_probe("ctrl-v-uppercase-does-not-emit-press")

    assert payload["emitted"] == []


def test_paste_on_text_input_emits_fill_action():
    payload = _run_actions_probe("paste-on-input-emits-fill")

    event = payload["emitted"][0]
    assert event["action"] == "fill"
    assert event["targetNodeName"] == "INPUT"
    assert event["payload"]["value"] == "test1"
    assert event["payload"]["signals"]["input_method"]["source_method"] == "paste"

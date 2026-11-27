"""Reason wording, runtime closure and operator preparation: pure, no model, no network."""

import json
from pathlib import Path
import re
import tempfile
import unittest

from harness_chat_reasons import (
    EXACT,
    FALLBACK,
    explain,
    explain_all,
    explain_turn_error,
)
from harness_chat_runtime import HERE, runtime_module_paths

# Design 8.4 "错误码怎么写成人话": every row, by code.
TABLE_84 = {
    "operator-chat-config-required": "本机还没有配置对话",
    "codex-login-required": "还没登录 Codex",
    "chat-operator-lease-expired": "对话许可已到期，发送关闭；已用额度和原回答保留",
    "chat-permit-not-current": "对话许可已到期，发送关闭；已用额度和原回答保留",
    "chat-config-changed": "配置或绑定变了，需要操作者重新核对",
    "chat-bound-file-changed:harness_chat.py": "配置或绑定变了，需要操作者重新核对",
    "chat-binding-file-pin-differs": "配置或绑定变了，需要操作者重新核对",
    "chat-cumulative-budget-exhausted": "调用次数已用完，不会自动追加",
    "chat-budget-config-differs": "额度记录和配置对不上，发送关闭，请联系操作者",
    "chat-budget-owned-by-another-store": "额度记录和配置对不上，发送关闭，请联系操作者",
    "chat-another-turn-running": "别处有一轮对话还没结束（或还没核对）",
    "chat-unresolved-turn-must-be-reconciled": "别处有一轮对话还没结束（或还没核对）",
    "chat-native-account-binding-differs": "现在登录的 Codex 账号和准备许可时的不是同一个",
    "chat-native-account-identity-missing": "现在登录的 Codex 账号和准备许可时的不是同一个",
    "codex-quota-below-15": "Codex 账号自己的额度不足 15%，或读不到额度，所以不发送",
    "codex-quota-unknown": "Codex 账号自己的额度不足 15%，或读不到额度，所以不发送",
    "codex-requested-model-unavailable": "许可里指定的模型或推理强度现在用不了",
    "codex-requested-effort-unavailable": "许可里指定的模型或推理强度现在用不了",
    "credential-required": "页面的登录信息失效了，请从 Wiki 首页重新打开",
    "chat-explicit-origin-required": "页面的登录信息失效了，请从 Wiki 首页重新打开",
    "chat-stage-material-reader-unavailable": "这一段的材料还没接通，对话关着",
    "chat-stage-not-supported": "这一段的材料还没接通，对话关着",
    "chat-session-content-cleared-open-new-session": "对话记录已清空（或课题已变），请开新对话",
    "chat-project-changed-open-new-session": "对话记录已清空（或课题已变），请开新对话",
    "chat-message-size-invalid": "消息是空的，或超过 8192 字节，没有发送",
    "chat-idempotency-conflict": "同一条消息已经发过，内容不一样，没有再发",
    "chat-continuation-reconcile-not-authorized": "这份许可下不能核对，请联系操作者",
    "chat-native-connection-lost-reconcile-required": "连接断了（或服务重启过），这一轮需要核对",
    "host-restarted-native-terminal-unconfirmed": "连接断了（或服务重启过），这一轮需要核对",
    "chat-response-too-large": "回答太长，没有保存",
}


class Reasons(unittest.TestCase):
    def test_every_design_row_is_worded_as_designed(self):
        for code, text in TABLE_84.items():
            self.assertEqual(explain(code)["text"], text, code)

    def test_unlisted_codes_fall_back_to_the_closed_sentence(self):
        for code in ("totally-new-code", "", None, "chat-tool-unknown"):
            self.assertEqual(explain(code)["text"], FALLBACK)

    def test_stage_context_refusals_all_mean_not_connected(self):
        for code in (
            "chat-stage-context-provider-unregistered",
            "chat-stage-provider-binding-differs",
            "chat-stage-required-evidence-missing",
        ):
            self.assertEqual(explain(code)["group"], "stage-unconnected", code)

    def test_text_never_contains_a_raw_code_and_explain_all_dedupes(self):
        for code, group, text in EXACT:
            self.assertNotIn(code, text)
            self.assertNotRegex(text, r"[a-z]+-[a-z]+-[a-z]+")
        both = explain_all(
            ["codex-quota-below-15", "codex-quota-below-15", "codex-quota-unknown"]
        )
        self.assertEqual(
            [x["code"] for x in both], ["codex-quota-below-15", "codex-quota-unknown"]
        )


class TurnErrors(unittest.TestCase):
    def test_failed_turn_reasons_follow_design_8_4(self):
        cases = {
            "chat-deadline-native-terminal-unconfirmed": "这一轮的结果还没确认",
            "ValueError:chat-unsupported-native-request:item/x": "Codex 请求了对话里不允许的操作",
            "ValueError:chat-event-thread-differs": "Codex 返回的内容和这一轮对不上",
            "ValueError:chat-terminal-binding-differs": "Codex 返回的内容和这一轮对不上",
            "ValueError:chat-response-too-large": "回答太长，没有保存",
            "ValueError:chat-rpc-eof": "和 Codex 的连接断了，需要核对",
            "TimeoutError:chat-rpc-reply-unknown:turn/start": "和 Codex 的连接断了，需要核对",
            "host-restarted-native-terminal-unconfirmed": "连接断了（或服务重启过），这一轮需要核对",
            "ValueError:codex-login-required": "还没登录 Codex",
            "RuntimeError:something-new": "这一轮没有完成，原始错误见技术细节",
        }
        for error, text in cases.items():
            self.assertEqual(explain_turn_error(error)["text"], text, error)
            self.assertEqual(explain_turn_error(error)["code"], error)
        self.assertIsNone(explain_turn_error(None))
        self.assertIsNone(explain_turn_error(""))


class Closure(unittest.TestCase):
    def test_runtime_closure_stays_inside_harness_ui_and_uses_mainline_channel(self):
        modules = runtime_module_paths()
        self.assertEqual(
            Path(modules["native_stage1"]).resolve(),
            (HERE / "native_stage1.py").resolve(),
        )
        for name, path in modules.items():
            self.assertTrue(Path(path).resolve().is_relative_to(HERE.resolve()), name)
        self.assertIn("harness_chat", modules)
        self.assertNotIn("local_reuse_chat_tools", modules)

    def test_no_ported_source_names_a_ui_work_path(self):
        names = [
            p
            for p in HERE.glob("*.py")
            if p.name.startswith(("harness_chat", "chat_", "current_chat"))
        ]
        self.assertGreater(len(names), 10)
        for path in names:
            if path.name.startswith("test_") or path.name == "chat_test_fixtures.py":
                continue
            text = path.read_text(encoding="utf-8")
            for forbidden in (
                "UI/work",
                "v7-functional-candidate",
                "v9-ui-stage12",
                "D:/Codex_Learning",
                "harness_ui/",
            ):
                self.assertNotIn(forbidden, text, (path.name, forbidden))
            self.assertIsNone(re.search(r"[A-Z]:[\\/]", text), path.name)

    def test_operator_prepare_writes_a_manifest_outside_git_and_creates_no_grant(self):
        from chat_operator_prepare import prepare

        with tempfile.TemporaryDirectory(prefix="chat-prepare-") as temporary:
            base = Path(temporary).resolve()
            exe, config = base / "codex.exe", base / "config.toml"
            exe.write_bytes(b"fixture, never executed")
            config.write_text("", encoding="utf-8")
            result = prepare(base / "observation", exe, config)
            self.assertEqual(
                (
                    result["message_permit_created"],
                    result["send_ready"],
                    result["model_messages"],
                ),
                (False, False, 0),
            )
            manifest = json.loads(
                (base / "observation" / "runtime-binding.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["kind"], "V9ChatRuntimeBinding")
            self.assertIn("native_stage1", manifest["modules"])
            self.assertEqual(sorted(p.name for p in base.rglob("*.sqlite3")), [])
            with self.assertRaisesRegex(
                ValueError, "new-absolute-observation-directory-required"
            ):
                prepare(base / "observation", exe, config)
            with self.assertRaisesRegex(ValueError, "outside-git"):
                prepare(HERE / "never-created", exe, config)


if __name__ == "__main__":
    unittest.main(verbosity=2)
